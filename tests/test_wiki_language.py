#!/usr/bin/env python3
"""Generated prose follows the configured wiki language (issue #1).

`SOUL.md`, `schema/CONTENT_POLICY.md` and the generated directory indexes are
maintained prose, so the wiki-language contract applies to them like to every
other page. Until this module existed no test ran with a wiki language other
than `de`, which is how both identity files and every directory index came to
be German for every wiki regardless of its configuration.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import identity_contract  # noqa: E402
import navigation  # noqa: E402
from harness import IDENTITY, MAINTAIN, TempWiki, Wiki, run, run_json  # noqa: E402
from test_lifecycle import SOURCE_MARKDOWN  # noqa: E402


GERMAN_MARKERS = (
    "Diese Datei",
    "Zweck und Wissensarten",
    "Zielgruppe",
    "Tonalität und Antwortstil",
    "Grenzen und Tabus",
    "Aktualisierungsmodell",
    "Ersetzung",
    "Entfernung",
    "Widersprüche",
)
ENGLISH_SOUL_HEADINGS = (
    "## Purpose and knowledge types",
    "## Audience",
    "## Tone and answer style",
    "## Boundaries and taboos",
)
ENGLISH_POLICY_HEADINGS = ("## Update model", "## Supersession", "## Removal", "## Conflicts")

#: What the generator wrote for the harness identity before it knew a wiki
#: language (commit 620c6d4). German wikis must keep getting exactly this.
GERMAN_SOUL = '''---
soul_version: 1
status: "confirmed"
purpose: "Test the SkillSafeWerkstatt contract end to end."
knowledge_types:
  - "concept"
  - "entity"
audience: "Maintainers of this repository."
answer_language: "de"
form_of_address: "Sie"
tone: "neutral"
detail: "medium"
answer_structure: "Antwort, dann Belege."
citation_display: "claim_id, Titel, Quelle"
uncertainty_style: "Unsicherheit ausdruecklich benennen."
history_presentation: "Abgeloestes als Historie kennzeichnen."
boundaries: "Nur belegtes Wissen aus diesem Wiki."
taboos: "Keine erfundenen Quellen."
---

# SOUL

Diese Datei beschreibt die bestätigte Identität und Antwortform dieses Wissensraums.
Sie steuert keine Berechtigungen und ändert keine belegten Inhalte.

## Zweck und Wissensarten

Test the SkillSafeWerkstatt contract end to end.

- concept
- entity

## Zielgruppe

Maintainers of this repository.

## Tonalität und Antwortstil

- Antwortsprache: de
- Anrede: Sie
- Tonalität: neutral
- Ausführlichkeit: medium
- Antwortstruktur: Antwort, dann Belege.
- Quellenanzeige: claim_id, Titel, Quelle
- Unsicherheit: Unsicherheit ausdruecklich benennen.
- Historie in Antworten: Abgeloestes als Historie kennzeichnen.

## Grenzen und Tabus

Grenzen: Nur belegtes Wissen aus diesem Wiki.

Tabus: Keine erfundenen Quellen.
'''

GERMAN_POLICY = '''---
policy_version: 1
status: "confirmed"
update_model: "current-state"
supersession_policy: "Neuere belegte Aussage ersetzt aeltere nur ausdruecklich."
removal_policy: "preview-confirm-never-automatic"
conflict_policy: "preserve-and-disclose"
---

# Content policy

Diese Datei steuert die Pflege von aktuellem, historischem, ersetztem und
widersprüchlichem Wissen. Sie verändert oder löscht nichts automatisch.

## Aktualisierungsmodell

current-state

## Ersetzung

Neuere belegte Aussage ersetzt aeltere nur ausdruecklich.

## Entfernung

Entfernungsvorschläge benötigen immer eine Vorschau und eine ausdrückliche
Bestätigung. Quellen, Claims, Seiten und Historie werden niemals automatisch
gelöscht.

## Widersprüche

Belegte widersprüchliche Positionen bleiben erhalten und werden offengelegt,
bis ihre Anwendbarkeit oder Ersetzung belastbar geklärt ist.
'''


def plan_for(language: str, identity: dict = IDENTITY) -> dict:
    return identity_contract.build_plan({**identity, "wiki_language": language})


def body_of(markdown: str) -> str:
    """The rendered prose after the frontmatter block."""
    return markdown.split("---", 2)[2]


class RenderedIdentity(unittest.TestCase):
    def test_an_english_wiki_gets_english_scaffolding(self) -> None:
        plan = plan_for("en")
        soul, policy = body_of(plan["soul_markdown"]), body_of(plan["content_policy_markdown"])
        for heading in ENGLISH_SOUL_HEADINGS:
            self.assertIn(heading, soul)
        for heading in ENGLISH_POLICY_HEADINGS:
            self.assertIn(heading, policy)
        for marker in GERMAN_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, soul)
                self.assertNotIn(marker, policy)

    def test_a_german_wiki_gets_exactly_what_it_got_before(self) -> None:
        plan = plan_for("de")
        self.assertEqual(plan["soul_markdown"], GERMAN_SOUL)
        self.assertEqual(plan["content_policy_markdown"], GERMAN_POLICY)

    def test_field_values_are_written_as_given_in_every_language(self) -> None:
        """The scaffolding follows the wiki language; the confirmed values never move."""
        soul = body_of(plan_for("en")["soul_markdown"])
        self.assertIn("- Form of address: Sie", soul)
        self.assertIn("- Answer structure: Antwort, dann Belege.", soul)
        self.assertIn("Taboos: Keine erfundenen Quellen.", soul)

    def test_regional_codes_use_their_primary_language(self) -> None:
        self.assertIn("## Audience", plan_for("en-GB")["soul_markdown"])
        self.assertIn("## Zielgruppe", plan_for("de-AT")["soul_markdown"])

    def test_an_unsupported_code_falls_back_to_english(self) -> None:
        plan = plan_for("fr")
        self.assertIn("## Audience", plan["soul_markdown"])
        self.assertIn("## Conflicts", plan["content_policy_markdown"])
        self.assertEqual(plan["wiki_language"], "fr")

    def test_the_language_is_part_of_the_hash(self) -> None:
        german, english = plan_for("de"), plan_for("en")
        self.assertEqual(german["identity"], english["identity"])
        self.assertNotEqual(german["proposal_sha256"], english["proposal_sha256"])
        self.assertEqual(english["wiki_language"], "en")
        self.assertEqual(english["format"], identity_contract.PLAN_FORMAT)

    def test_a_plan_without_a_language_is_refused(self) -> None:
        with self.assertRaises(identity_contract.IdentityError):
            identity_contract.build_plan(dict(IDENTITY))

    def test_an_invalid_code_is_refused(self) -> None:
        for code in ("", "german", "de_DE", "e"):
            with self.subTest(code=code), self.assertRaises(identity_contract.IdentityError):
                plan_for(code)

    def test_a_plan_for_another_language_is_refused_by_the_guard(self) -> None:
        plan = plan_for("de")
        identity_contract.require_plan_language(plan, "DE", "the test")
        with self.assertRaises(identity_contract.IdentityError) as caught:
            identity_contract.require_plan_language(plan, "en", "the test")
        self.assertIn("'de'", str(caught.exception))
        self.assertIn("'en'", str(caught.exception))


class Planner(unittest.TestCase):
    """The command-line entrypoint the maintenance skill actually calls."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="lmwiki-planner-"))
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.input = self.directory / "identity.json"
        self.input.write_text(json.dumps(IDENTITY, ensure_ascii=False), encoding="utf-8")

    def test_the_wiki_language_is_required(self) -> None:
        result = run(MAINTAIN / "plan_identity.py", "--input", str(self.input), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--wiki-language", result.stderr)

    def test_the_plan_records_the_language(self) -> None:
        plan = run_json(MAINTAIN / "plan_identity.py", "--input", str(self.input), "--wiki-language", "en")
        self.assertEqual(plan["wiki_language"], "en")
        self.assertIn("## Audience", plan["soul_markdown"])

    def test_a_conflicting_language_in_the_input_is_refused(self) -> None:
        self.input.write_text(json.dumps({**IDENTITY, "wiki_language": "de"}), encoding="utf-8")
        result = run(
            MAINTAIN / "plan_identity.py", "--input", str(self.input), "--wiki-language", "en", check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("differs", result.stderr)


def plan_file(directory: Path, language: str, identity: dict = IDENTITY) -> tuple[Path, str]:
    """Render one proposal through the real helper, as the skill does."""
    source = directory / f"identity-{language}.json"
    source.write_text(json.dumps(identity, ensure_ascii=False), encoding="utf-8")
    output = directory / f"plan-{language}.json"
    plan = run_json(
        MAINTAIN / "plan_identity.py", "--input", str(source), "--wiki-language", language, "--output", str(output)
    )
    return output, plan["proposal_sha256"]


class Guards(unittest.TestCase):
    def test_initialization_refuses_a_plan_for_another_language(self) -> None:
        directory = Path(tempfile.mkdtemp(prefix="lmwiki-guard-"))
        self.addCleanup(shutil.rmtree, directory, True)
        plan, digest = plan_file(directory, "de")
        target = directory / "wiki"
        result = run(
            MAINTAIN / "initialize_wiki.py",
            "--target", str(target),
            "--title", "T", "--topic", "X", "--wiki-language", "en",
            "--identity-plan", str(plan), "--expect-identity-sha256", digest,
            "--owner", "test/guard",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wiki language", (result.stdout + result.stderr).lower())
        self.assertFalse(target.exists() and any(target.iterdir()), "a refused initialization leaves nothing behind")

    def test_apply_refuses_a_plan_for_another_language(self) -> None:
        with TempWiki(language="en") as wiki:
            plan, digest = plan_file(wiki.root, "de")
            before = wiki.read("SOUL.md")
            history = sorted((wiki.path / "meta" / "history").glob("*")) if (wiki.path / "meta" / "history").is_dir() else []
            result = wiki.locked(
                "apply_identity.py",
                "--plan-file", str(plan), "--expect-proposal-sha256", digest, "--confirm-replace",
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("wiki language", (result.stdout + result.stderr).lower())
            self.assertEqual(wiki.read("SOUL.md"), before)
            after = sorted((wiki.path / "meta" / "history").glob("*")) if (wiki.path / "meta" / "history").is_dir() else []
            self.assertEqual(after, history, "a refused apply takes no snapshot")

    def test_apply_accepts_a_plan_for_the_wiki_language(self) -> None:
        with TempWiki(language="en") as wiki:
            revised = {**IDENTITY, "identity": {**IDENTITY["identity"], "tone": "warm"}}
            plan, digest = plan_file(wiki.root, "en", revised)
            wiki.locked(
                "apply_identity.py",
                "--plan-file", str(plan), "--expect-proposal-sha256", digest, "--confirm-replace",
            )
            soul = wiki.read("SOUL.md")
            self.assertIn('tone: "warm"', soul)
            self.assertIn("## Audience", soul)


def curate_english_page(wiki: Wiki, language: str) -> None:
    """One sourced page under `wiki/concepts/`, so a directory index is generated."""
    extract = wiki.root / "source.md"
    extract.write_text(SOURCE_MARKDOWN, encoding="utf-8")
    record = json.loads(
        wiki.locked(
            "register_source.py",
            "--markdown-file", str(extract),
            "--title", "Grid fees 2026",
            "--original-ref", "internal/grid-fees-2026.pdf",
            "--content-language", "de",
        ).stdout
    )["source"]
    wiki.write(
        "schema/CLUSTERS.md",
        wiki.read("schema/CLUSTERS.md").rstrip()
        + "\n\n## grid\n- Label: Grid\n- Color: #000099\n- Status: active\n- Purpose: Grid operation and fees\n",
    )
    wiki.write(
        "schema/CONCEPTS.md",
        wiki.read("schema/CONCEPTS.md").rstrip()
        + "\n\n## grid-fee\n- Preferred: Grid fee\n- Status: active\n"
        "- Definition: Charge for using the electricity grid\n- Aliases: Netzentgelt | network charge\n",
    )
    claim_id = json.loads(wiki.locked("claim_id.py", "--count", "1").stdout)["claim_ids"][0]
    relative = "wiki/concepts/grid-fee.md"
    page = f"""---
id: "concept-grid-fee"
title: "Grid fee"
type: "concept"
status: "active"
created: "2026-09-21"
updated: "2026-09-21"
description: "Basics and calculation of grid fees."
language: "{language}"
generated_by: "agent/test-suite"
generated_at: "2026-09-21T08:00:00Z"
sources:
  - "[[sources/{Path(record['path']).stem}|Grid fees 2026]]"
clusters:
  - "grid"
concepts:
  - "grid-fee"
tags:
  - "type/wiki-concept"
---

# Grid fee

## Summary

Grid fees are set once a year by the grid operator.

<!-- claim
id: {claim_id}
kind: fact
status: active
sources: {record['source_id']}@page=1
-->
The grid operator sets the grid fees every year.
<!-- /claim -->
"""
    staging = wiki.root / "staging"
    staged = staging / relative
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(page, encoding="utf-8")
    wiki.write("wiki/index.md", wiki.read("wiki/index.md").rstrip() + "\n- [[wiki/concepts/grid-fee|Grid fee]]\n")
    plan_path = wiki.root / "batch.json"
    wiki.locked(
        "page_batch.py", "plan",
        "--staging-dir", str(staging), "--paths-json", json.dumps([relative]), "--output", str(plan_path),
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    wiki.locked(
        "page_batch.py", "apply",
        "--staging-dir", str(staging), "--plan-file", str(plan_path), "--expect-plan-sha256", plan["plan_sha256"],
    )
    wiki.rebuild()


class EnglishWiki(unittest.TestCase):
    def test_the_identity_files_are_english(self) -> None:
        with TempWiki(language="en") as wiki:
            soul, policy = body_of(wiki.read("SOUL.md")), body_of(wiki.read("schema/CONTENT_POLICY.md"))
            for heading in ENGLISH_SOUL_HEADINGS:
                self.assertIn(heading, soul)
            for heading in ENGLISH_POLICY_HEADINGS:
                self.assertIn(heading, policy)
            for marker in GERMAN_MARKERS:
                self.assertNotIn(marker, soul + policy)
            self.assertEqual(wiki.verify()["state"], "ready")

    def test_a_directory_index_declares_the_wiki_language_and_releases(self) -> None:
        with TempWiki(language="en") as wiki:
            curate_english_page(wiki, "en")
            index = wiki.read("wiki/concepts/index.md")
            self.assertIn('language: "en"', index)
            self.assertIn("regenerated on every graph build", index)
            self.assertIn("Overview of the pages under wiki/concepts.", index)
            self.assertNotIn("Graphlauf", index)
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(wiki.release("english-1").returncode, 0)
            self.assertEqual(wiki.verify()["state"], "ready")
            self.assertEqual(wiki.verify(query_side=True)["state"], "ready")

    def test_a_regional_code_is_declared_verbatim(self) -> None:
        with TempWiki(language="en-GB") as wiki:
            curate_english_page(wiki, "en-GB")
            index = wiki.read("wiki/concepts/index.md")
            self.assertIn('language: "en-GB"', index)
            self.assertIn("regenerated on every graph build", index)
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])


class IndexProse(unittest.TestCase):
    def test_a_german_wiki_keeps_its_german_index(self) -> None:
        text = navigation.render_index("wiki/concepts/index.md", "concepts", [], "2026-01-01", "de")
        self.assertIn('language: "de"', text)
        self.assertIn("wird bei jedem Graphlauf neu erzeugt", text)
        self.assertIn("Diese Gruppe enthält derzeit keine Seiten.", text)

    def test_an_unknown_language_gets_english_prose_but_keeps_its_code(self) -> None:
        text = navigation.render_index("wiki/concepts/index.md", "concepts", [], "2026-01-01", "fr")
        self.assertIn('language: "fr"', text)
        self.assertIn("regenerated on every graph build", text)
        self.assertIn("This group currently holds no pages.", text)

    def test_the_language_comes_from_the_profile(self) -> None:
        with TempWiki(language="en") as wiki:
            self.assertEqual(navigation.wiki_language(wiki.path), "en")
        directory = Path(tempfile.mkdtemp(prefix="lmwiki-noprofile-"))
        self.addCleanup(shutil.rmtree, directory, True)
        self.assertEqual(navigation.wiki_language(directory), navigation.FALLBACK_LANGUAGE)


class Migration(unittest.TestCase):
    def test_the_preview_names_the_identity_re_render(self) -> None:
        with TempWiki() as wiki:
            preview = json.loads(
                wiki.locked("plan_language_migration.py", "--to-language", "en", "--to-label", "English").stdout
            )
            self.assertIn("SOUL.md", preview["affected_files"])
            self.assertTrue(
                any("apply_identity.py" in action and "plan_identity.py" in action for action in preview["required_actions"]),
                preview["required_actions"],
            )


if __name__ == "__main__":
    unittest.main()
