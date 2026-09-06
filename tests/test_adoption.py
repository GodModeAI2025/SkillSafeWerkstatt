#!/usr/bin/env python3
"""Adopting an existing Markdown collection into a wiki.

An Obsidian vault or a documentation folder is material that already exists;
re-typing it one registration at a time is not a contract, it is friction. But
bulk import is exactly the shape of the mistake this wiki is built to prevent:
content in `wiki/` with nothing behind it.

Adoption resolves that by importing **evidence, not knowledge**. Each accepted
file is registered as a source like any other, with its own identifier, hash and
portable reference, and no page is created. These tests pin that boundary as
firmly as the plan/apply mechanics around it.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import TempWiki  # noqa: E402


PAGE = """---
title: "Netzentgelte 2026"
tags: ["energie"]
---

# Netzentgelte 2026

Der Arbeitspreis steigt zum 1. Januar.
"""

PLAIN = "# Bilanzkreis\n\nEin Bilanzkreis buendelt Einspeisung und Entnahme.\n"


class Adoption(unittest.TestCase):
    def collection(self, wiki, files: dict[str, str]) -> Path:
        root = wiki.root / "vault"
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    def plan(self, wiki, root: Path, check: bool = True):
        output = wiki.root / "adoption-plan.json"
        result = wiki.locked(
            "adopt_directory.py",
            "plan",
            "--source-dir", str(root),
            "--content-language", "de",
            "--output", str(output),
            check=check,
        )
        return json.loads(result.stdout), output

    def apply(self, wiki, root: Path, plan, output: Path, *accepted: str, check: bool = False):
        arguments = ["--source-dir", str(root), "--plan-file", str(output),
                     "--expect-plan-sha256", plan["plan_sha256"]]
        for path in accepted:
            arguments += ["--accept", path]
        return wiki.locked("adopt_directory.py", "apply", *arguments, check=check)

    # -- planning ----------------------------------------------------------

    def test_the_plan_finds_the_markdown_and_changes_nothing(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"netzentgelte.md": PAGE, "sub/bilanzkreis.md": PLAIN})
            before = sorted(p.name for p in (wiki.path / "sources").glob("*"))
            plan, _ = self.plan(wiki, root)
            self.assertEqual(plan["summary"]["found"], 2)
            self.assertEqual(plan["summary"]["adoptable"], 2)
            self.assertEqual(sorted(p.name for p in (wiki.path / "sources").glob("*")), before)

    def test_the_title_comes_from_the_document_itself(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PAGE, "b.md": PLAIN, "c.md": "kein Titel\n"})
            plan, _ = self.plan(wiki, root)
            titles = {item["path"]: item.get("title") for item in plan["candidates"]}
            self.assertEqual(titles["a.md"], "Netzentgelte 2026")  # frontmatter
            self.assertEqual(titles["b.md"], "Bilanzkreis")  # first heading
            self.assertEqual(titles["c.md"], "c")  # the file name, last

    def test_non_markdown_is_reported_rather_than_silently_dropped(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN, "bild.png": "x", "notizen.txt": "y"})
            plan, _ = self.plan(wiki, root)
            self.assertEqual(plan["skipped_non_markdown_total"], 2)
            self.assertIn("bild.png", plan["skipped_non_markdown"])

    def test_an_empty_file_is_blocked_with_its_reason(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"leer.md": "   \n", "voll.md": PLAIN})
            plan, _ = self.plan(wiki, root)
            blocked = {item["path"]: item for item in plan["candidates"] if not item["adoptable"]}
            self.assertIn("leer.md", blocked)
            self.assertTrue(blocked["leer.md"]["blockers"])

    def test_an_operating_system_artifact_is_not_a_candidate(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            (root / ".DS_Store").write_text("x", encoding="utf-8")
            (root / "desktop.ini").write_text("x", encoding="utf-8")
            plan, _ = self.plan(wiki, root)
            self.assertEqual(plan["summary"]["adoptable"], 1)

    def test_the_plan_states_what_adoption_is_not(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            plan, _ = self.plan(wiki, root)
            self.assertIn("evidence, not knowledge", plan["boundary"])

    def test_a_collection_inside_the_wiki_is_refused(self) -> None:
        with TempWiki() as wiki:
            inside = wiki.path / "sources"
            result = wiki.locked(
                "adopt_directory.py", "plan", "--source-dir", str(inside), check=False
            )
            self.assertNotEqual(result.returncode, 0)

    # -- applying ----------------------------------------------------------

    def test_only_the_accepted_files_are_registered(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PAGE, "b.md": PLAIN})
            plan, output = self.plan(wiki, root)
            result = self.apply(wiki, root, plan, output, "a.md")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            applied = json.loads(result.stdout)
            self.assertEqual(applied["writes"], 1)
            self.assertEqual(applied["registered"][0]["path"], "a.md")

            registry = (wiki.path / "meta" / "sources.jsonl").read_text(encoding="utf-8")
            records = [json.loads(line) for line in registry.splitlines() if line.strip()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source_type"], "adopted")
            self.assertEqual(records[0]["original_ref"], "a.md")

    def test_nothing_lands_in_the_curated_layer(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PAGE, "b.md": PLAIN})
            pages_before = sorted(p.name for p in (wiki.path / "wiki").rglob("*.md"))
            plan, output = self.plan(wiki, root)
            self.apply(wiki, root, plan, output, "a.md", "b.md", check=True)
            self.assertEqual(
                sorted(p.name for p in (wiki.path / "wiki").rglob("*.md")),
                pages_before,
                "adoption imports evidence; a wiki page stays deliberate curation",
            )

    def test_the_adopted_material_leaves_the_wiki_valid(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PAGE, "sub/b.md": PLAIN})
            plan, output = self.plan(wiki, root)
            self.apply(wiki, root, plan, output, "a.md", "sub/b.md", check=True)
            wiki.rebuild()
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["stats"]["registered_sources"], 2)

    def test_a_snapshot_is_taken_before_the_first_write(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            plan, output = self.plan(wiki, root)
            applied = json.loads(self.apply(wiki, root, plan, output, "a.md").stdout)
            self.assertTrue(applied["snapshot"]["snapshot_id"])

    def test_the_result_says_the_curation_still_has_to_happen(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            plan, output = self.plan(wiki, root)
            applied = json.loads(self.apply(wiki, root, plan, output, "a.md").stdout)
            self.assertTrue(any("wiki/" in step for step in applied["next_steps"]))

    def test_selecting_nothing_writes_nothing(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            plan, output = self.plan(wiki, root)
            applied = json.loads(self.apply(wiki, root, plan, output).stdout)
            self.assertEqual(applied["state"], "nothing_selected")
            self.assertEqual(applied["writes"], 0)

    # -- the plan binds ----------------------------------------------------

    def test_a_file_changed_after_confirmation_stops_every_write(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN, "b.md": PAGE})
            plan, output = self.plan(wiki, root)
            (root / "b.md").write_text(PLAIN + "\nNachtraeglich geaendert.\n", encoding="utf-8")
            result = self.apply(wiki, root, plan, output, "a.md", "b.md")
            self.assertNotEqual(result.returncode, 0)
            applied = json.loads(result.stdout)
            self.assertEqual(applied["state"], "stale_plan")
            self.assertEqual(applied["writes"], 0, "a drift must not half-apply the selection")
            self.assertFalse((wiki.path / "meta" / "sources.jsonl").read_text(encoding="utf-8").strip())

    def test_a_modified_plan_is_refused(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            plan, output = self.plan(wiki, root)
            tampered = json.loads(output.read_text(encoding="utf-8"))
            tampered["candidates"][0]["title"] = "Etwas ganz anderes"
            output.write_text(json.dumps(tampered), encoding="utf-8")
            result = self.apply(wiki, root, plan, output, "a.md")
            self.assertNotEqual(result.returncode, 0)

    def test_a_path_that_is_not_in_the_plan_is_refused(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            plan, output = self.plan(wiki, root)
            result = self.apply(wiki, root, plan, output, "gibt-es-nicht.md")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["state"], "invalid_selection")

    def test_a_blocked_file_cannot_be_accepted_anyway(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"leer.md": "\n"})
            plan, output = self.plan(wiki, root)
            result = self.apply(wiki, root, plan, output, "leer.md")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["state"], "blocked_selection")

    def test_material_already_registered_is_not_adopted_twice(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            plan, output = self.plan(wiki, root)
            self.apply(wiki, root, plan, output, "a.md", check=True)

            again, output2 = self.plan(wiki, root)
            entry = again["candidates"][0]
            self.assertFalse(entry["adoptable"])
            self.assertTrue(any("already registered" in item for item in entry["blockers"]))

    def test_adoption_requires_the_lock(self) -> None:
        with TempWiki() as wiki:
            root = self.collection(wiki, {"a.md": PLAIN})
            result = wiki.maintain(
                "adopt_directory.py",
                "plan",
                "--target", str(wiki.path),
                "--lock-token", "lk_nicht-echt",
                "--source-dir", str(root),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
