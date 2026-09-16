#!/usr/bin/env python3
"""Credentials stay out of the wiki, and out of every report about them.

The credentials below are assembled at runtime so that neither this repository
nor a push-protection scanner ever sees a complete one in the source text.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import secret_screen  # noqa: E402
from harness import TempWiki  # noqa: E402
from validate_extraction import assess  # noqa: E402


ACCESS_KEY = "AKIA" + "Q7XW3M" + "PLN2RZT4KV"
URL_PASSWORD = "geheim" + "123"
URL = "https" + "://reader:" + URL_PASSWORD + "@wiki.example.org/api"
KEY_BLOCK = "-----BEGIN " + "RSA PRIVATE KEY-----"


class Screen(unittest.TestCase):
    def test_each_credential_form_is_recognized(self) -> None:
        for text, kind in (
            (f"Zugang: {ACCESS_KEY}", "aws-access-key"),
            (f"Endpunkt {URL}", "url-credentials"),
            (KEY_BLOCK, "private-key"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(secret_screen.scan_text(f"eins\n{text}\n"), [(2, kind)])

    def test_ordinary_prose_and_links_are_not_findings(self) -> None:
        text = (
            "Siehe https://example.org/a:b und git@github.com:org/repo.git.\n"
            "risk-management-and-knowledge-sharing-guidelines-for-teams\n"
            "Ein Passwort gehört nie in das Wiki.\n"
        )
        self.assertEqual(secret_screen.scan_text(text), [])

    def test_documentation_placeholders_are_not_findings(self) -> None:
        text = (
            "postgres://user:password@localhost/db\n"
            "https://bot:${TOKEN}@ci.example.org\n"
            "AKIA" + "IOSFODNN7EXAMPLE\n"
            "gh" + "p_" + "x" * 36 + "\n"
            "sk-" + "proj-" + "X" * 40 + "\n"
            "task-sk-" + "abcdefghijklmnopqrstuvwxyz0123456789\n"
        )
        self.assertEqual(secret_screen.scan_text(text), [])
        self.assertEqual(
            secret_screen.scan_text(f"postgres://user:password@localhost/db {URL}\n"),
            [(1, "url-credentials")],
        )

    def test_a_report_line_never_repeats_the_value(self) -> None:
        lines = secret_screen.describe("wiki/overview.md", secret_screen.scan_text(URL))
        self.assertEqual(len(lines), 1)
        self.assertIn("wiki/overview.md:1", lines[0])
        self.assertNotIn(URL_PASSWORD, lines[0])


class Preflight(unittest.TestCase):
    def test_an_extraction_carrying_a_credential_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "extraction.md"
            path.write_text(f"# Handbuch\n\nSchlüssel: {ACCESS_KEY}\n", encoding="utf-8")
            report = assess(path)
        self.assertEqual(report["state"], "rejected")
        self.assertTrue(any("possible credential" in item for item in report["errors"]))
        self.assertNotIn(ACCESS_KEY, json.dumps(report))


class InTheWiki(unittest.TestCase):
    def test_a_clean_wiki_passes(self) -> None:
        with TempWiki() as wiki:
            report = json.loads(wiki.lint().stdout)
            self.assertTrue(report["valid"], report["errors"])

    def test_a_credential_on_a_page_fails_the_lint_without_being_echoed(self) -> None:
        with TempWiki() as wiki:
            page = wiki.path / "wiki" / "overview.md"
            page.write_text(
                page.read_text(encoding="utf-8") + f"\nEndpunkt: {URL}\n", encoding="utf-8"
            )
            result = wiki.lint()
            report = json.loads(result.stdout)
            self.assertFalse(report["valid"])
            self.assertTrue(
                any(
                    item.startswith("wiki/overview.md:") and "url-credentials" in item
                    for item in report["errors"]
                ),
                report["errors"],
            )
            self.assertNotIn(URL_PASSWORD, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
