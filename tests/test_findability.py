#!/usr/bin/env python3
"""Findability questions (Stufe 5, package C, owner decision E3).

`findability_questions.py add|remove|check` keeps questions the owner or real
users asked, each with its confirmed target claim, in
meta/findability-questions.jsonl. The file lies outside the release: it is
never hashed, verified, snapshotted by default, or exported. `add` stores the
wording verbatim and only with `--user-supplied-wording`; `check` loads the
working files once and ranks every question with the query skill's search
core. Nothing here ever blocks a release.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any, Optional
from unittest import mock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import findability_questions  # noqa: E402
from harness import MAINTAIN, TempWiki, Wiki  # noqa: E402
from test_lifecycle import SOURCE_MARKDOWN, add_cluster_and_concept  # noqa: E402

RELATIVE = "meta/findability-questions.jsonl"
QUESTION = "wie lang hab ich zeit zum kündigen wenn ich umziehe"


def claim_block(claim_id: str, status: str, text: str, source_id: str) -> str:
    return f"<!-- claim\nid: {claim_id}\nkind: fact\nstatus: {status}\nsources: {source_id}@page=1\n-->\n{text}\n<!-- /claim -->"


def content_page(slug: str, title: str, source: tuple[str, str], claims: list[str]) -> str:
    source_id, stem = source
    body = "\n\n".join(claims)
    return f"""---
id: "topic-{slug}"
title: "{title}"
type: "topic"
status: "active"
created: "2026-09-06"
updated: "2026-09-06"
description: "{title}."
language: "de"
sources:
  - "[[sources/{stem}|Netzentgelte 2026]]"
clusters:
  - "netz"
concepts: []
tags:
  - "type/wiki-topic"
---

# {title}

{body}
"""


class FindabilityWiki:
    """A released wiki with two topic pages and five claims."""

    def __init__(self, wiki: Wiki) -> None:
        self.wiki = wiki
        record = wiki.register_source(SOURCE_MARKDOWN, "Netzentgelte 2026", "intern/netzentgelte-2026.pdf")
        self.source = (record["source_id"], Path(record["path"]).stem)
        add_cluster_and_concept(wiki)
        ids = json.loads(wiki.locked("claim_id.py", "--count", "5").stdout)["claim_ids"]
        self.cancel, self.address, self.advance, self.old_advance, self.spare = ids
        index = wiki.read("wiki/index.md").rstrip()
        wiki.write("wiki/index.md", index + "\n\n- [[wiki/topics/umzug|Umzug]]\n- [[wiki/topics/abschlag|Abschlag]]\n")
        wiki.apply_pages({"wiki/topics/umzug.md": self.umzug(), "wiki/topics/abschlag.md": self.abschlag()})
        wiki.rebuild()
        wiki.release("findability-setup")

    def umzug(self, *, with_spare: bool = True, address_status: str = "active") -> str:
        claims = [
            claim_block(self.cancel, "active",
                        "Bei einem Umzug kann der Kunde den Vertrag mit einer Frist von sechs Wochen kündigen.", self.source[0]),
            claim_block(self.address, address_status,
                        "Die neue Anschrift ist dem Lieferanten schriftlich mitzuteilen.", self.source[0]),
        ]
        if with_spare:
            claims.append(claim_block(self.spare, "active", "Die Schlussrechnung folgt nach dem Auszug.", self.source[0]))
        return content_page("umzug", "Umzug", self.source, claims)

    def abschlag(self, *, advance_status: str = "active") -> str:
        return content_page("abschlag", "Abschlag", self.source, [
            claim_block(self.advance, advance_status,
                        "Der monatliche Abschlag wird aus dem Vorjahresverbrauch berechnet.", self.source[0]),
            claim_block(self.old_advance, "superseded", "Der Abschlag wurde früher quartalsweise gezahlt.", self.source[0]),
        ])

    def helper(self, *args: str, stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
        """findability_questions.py through run_locked.py under a fresh lock, with optional standard input."""
        token_file = self.wiki.root / f"runtime-token-{uuid4().hex}"
        self.wiki.maintain("wiki_lock.py", "acquire", "--target", str(self.wiki.path), "--token-file", str(token_file),
                           "--owner", "test/harness")
        try:
            return subprocess.run(
                [sys.executable, str(MAINTAIN / "run_locked.py"), "--token-file", str(token_file),
                 "--helper", "findability_questions.py", "--", args[0], "--target", str(self.wiki.path), *args[1:]],
                input=stdin if stdin is not None else b"",
                capture_output=True,
                cwd=str(MAINTAIN),
            )
        finally:
            self.wiki.maintain("wiki_lock.py", "release", "--target", str(self.wiki.path), "--token-file",
                               str(token_file), check=False)

    def ok(self, *args: str, stdin: Optional[bytes] = None) -> dict[str, Any]:
        result = self.helper(*args, stdin=stdin)
        if result.returncode != 0:
            raise AssertionError(result.stderr.decode("utf-8", errors="replace"))
        return json.loads(result.stdout.decode("utf-8"))

    def refused(self, *args: str, stdin: Optional[bytes] = None) -> str:
        result = self.helper(*args, stdin=stdin)
        if result.returncode == 0:
            raise AssertionError(f"accepted: {result.stdout.decode('utf-8')}")
        if result.stdout:
            raise AssertionError(f"a refusal prints nothing on stdout: {result.stdout!r}")
        return result.stderr.decode("utf-8").strip()

    def add(self, question: str, claim_id: str, *extra: str) -> dict[str, Any]:
        return self.ok("add", "--question", question, "--claim-id", claim_id, "--author", "user",
                       "--user-supplied-wording", *extra)

    def records(self) -> list[dict[str, Any]]:
        path = self.wiki.path / RELATIVE
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Recording(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = TempWiki()
        cls.fw = FindabilityWiki(cls._temp.__enter__())

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.__exit__(None, None, None)

    def setUp(self) -> None:
        (self.fw.wiki.path / RELATIVE).unlink(missing_ok=True)

    def test_add_requires_user_supplied_wording(self) -> None:
        message = self.fw.refused("add", "--question", QUESTION, "--claim-id", self.fw.cancel, "--author", "user")
        self.assertIn("findability questions must be the owner's or a user's own words", message)
        self.assertFalse((self.fw.wiki.path / RELATIVE).exists())

    def test_add_records_the_wording_verbatim(self) -> None:
        wording = "  Wie lang hab ich Zeit zum kündigen wenn ich umzihe??  "
        report = self.fw.add(wording, self.fw.cancel, "--note", "Telefon, Oktober")
        record = report["question"]
        self.assertEqual((report["recorded"], report["path"]), (True, RELATIVE))
        self.assertEqual(record["question"], wording.strip())
        self.assertEqual(sorted(record), sorted(findability_questions.RECORD_KEYS))
        self.assertRegex(record["question_id"], r"^fq-[0-9a-f]{16}$")
        self.assertRegex(record["added_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual((record["author"], record["claim_id"], record["note"]), ("user", self.fw.cancel, "Telefon, Oktober"))
        self.assertEqual(record["format"], "lmwiki-findability-question/1")
        self.assertTrue(record["lock_id"])
        self.assertEqual(self.fw.records(), [record])
        raw = (self.fw.wiki.path / RELATIVE).read_bytes()
        self.assertEqual(raw, (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))

    def test_add_reads_the_wording_from_standard_input(self) -> None:
        wording = 'Kann ich beim Umzug kündigen? Mein Vermieter sagt "sofort" und der Nachbar meint\'s geht nicht – stimmt\'s?'
        escaped = json.dumps({"query": wording}, ensure_ascii=True).encode("ascii")
        self.assertNotIn(b"\xc3", escaped)
        from_stdin = self.fw.ok("add", "--question", "-", "--claim-id", self.fw.cancel, "--author", "owner",
                                "--user-supplied-wording", stdin=escaped)["question"]
        self.assertEqual(from_stdin["question"], wording)
        (self.fw.wiki.path / RELATIVE).unlink()
        from_argv = self.fw.ok("add", "--question", wording, "--claim-id", self.fw.cancel, "--author", "owner",
                               "--user-supplied-wording")["question"]
        self.assertEqual({key: from_stdin[key] for key in ("question", "claim_id", "author", "note", "format")},
                         {key: from_argv[key] for key in ("question", "claim_id", "author", "note", "format")})
        stdin_arguments = ("add", "--question", "-", "--claim-id", self.fw.cancel, "--author", "user", "--user-supplied-wording")
        for body in ({"query": "Umzug", "also": ["Wohnungswechsel"]}, {"query": "Umzug", "filter": {"kind": "all"}}):
            with self.subTest(body=body):
                message = self.fw.refused(*stdin_arguments, stdin=json.dumps(body).encode("utf-8"))
                self.assertEqual(message, 'a findability question is one wording; send only {"query": ...}')
        message = self.fw.refused(*stdin_arguments, stdin='{"query": "K?ndigung beim Umzug"}'.encode("utf-8"))
        self.assertTrue(message.startswith("question input is invalid: query looks re-encoded"), message)
        self.assertEqual(len(self.fw.records()), 1)

    def test_line_separators_and_question_marks_in_a_wording_survive(self) -> None:
        stdin_arguments = ("add", "--question", "-", "--claim-id", self.fw.cancel, "--author", "user", "--user-supplied-wording")
        # U+2028, U+2029 and U+0085 are line ends to str.splitlines(): written raw, one
        # record read back as two broken lines and stopped every later add, check and remove.
        wording = "Umzug melden:\u2028wie lang ist die Frist\u2029und\u0085wann"
        first = self.fw.ok(*stdin_arguments, stdin=json.dumps({"query": wording}).encode("ascii"))["question"]
        self.assertEqual(first["question"], wording)
        text = (self.fw.wiki.path / RELATIVE).read_text(encoding="utf-8")
        self.assertEqual(len(text.splitlines()), 1)
        self.assertIn("\\u2028", text)
        # A real "?" before a letter arrives as \u003f; a literal one there still looks re-encoded.
        verbatim = "kann ich beim umzug kündigen?danke"
        escaped = json.dumps({"query": verbatim}).replace("?", "\\u003f").encode("ascii")
        second = self.fw.ok(*stdin_arguments, stdin=escaped)["question"]
        self.assertEqual(second["question"], verbatim)
        self.assertEqual(
            self.fw.refused(*stdin_arguments, stdin=json.dumps({"query": verbatim}).encode("ascii")),
            "question input is invalid: query looks re-encoded on the way (a ? before a letter, or U+FFFD); escape "
            "every non-ASCII character as \\uXXXX, and write a ? that really stands before a letter as \\u003f",
        )
        # The shared reader's messages name this helper's flag.
        self.assertEqual(self.fw.refused(*stdin_arguments, stdin=b""),
                         "question input is invalid: empty input; pipe one JSON object to --question -")
        report = self.fw.ok("check")
        self.assertEqual([result["question"] for result in report["results"]], [wording, verbatim])
        self.fw.ok("remove", "--question-id", first["question_id"])
        self.assertEqual(self.fw.records(), [second])
        # A file an earlier version wrote with a raw separator and CRLF line ends reads back too.
        (self.fw.wiki.path / RELATIVE).write_bytes(
            (json.dumps(first, ensure_ascii=False, sort_keys=True) + "\r\n").encode("utf-8")
        )
        self.assertEqual(self.fw.ok("check")["questions"], 1)

    def test_add_refuses_invalid_input(self) -> None:
        self.fw.add(QUESTION, self.fw.cancel)
        cases = {
            "empty": (("--question", "   ", "--claim-id", self.fw.cancel), "question must contain 1 to 500 characters"),
            "long": (("--question", "a" * 501, "--claim-id", self.fw.cancel), "question must contain 1 to 500 characters"),
            "no word": (("--question", "?? !!", "--claim-id", self.fw.cancel), "question contains no searchable word"),
            "credential": (("--question", "Mein Token ist ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "--claim-id", self.fw.cancel),
                           "question contains a credential-shaped value"),
            "claim format": (("--question", "Abschlag", "--claim-id", "clm-xyz"), "claim-id must look like clm-<16 hex digits>"),
            "unknown claim": (("--question", "Abschlag", "--claim-id", "clm-0123456789abcdef"),
                              "claim clm-0123456789abcdef does not exist in this wiki"),
            "superseded": (("--question", "Abschlag", "--claim-id", self.fw.old_advance),
                           f"claim {self.fw.old_advance} has status superseded; a findability question targets an active or disputed claim"),
            "duplicate": (("--question", f"  {QUESTION} ", "--claim-id", self.fw.cancel), "this question already targets"),
            "long note": (("--question", "Abschlag", "--claim-id", self.fw.advance, "--note", "x" * 201),
                          "note must be one line of at most 200 characters"),
        }
        for name, (arguments, expected) in cases.items():
            with self.subTest(case=name):
                message = self.fw.refused("add", *arguments, "--author", "user", "--user-supplied-wording")
                self.assertTrue(message.startswith(expected), message)
        self.assertEqual(len(self.fw.records()), 1)
        template = self.fw.records()[0]
        filled = [{**template, "question_id": f"fq-{number:016x}", "question": f"Frage {number}"} for number in range(200)]
        (self.fw.wiki.path / RELATIVE).write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in filled), encoding="utf-8"
        )
        message = self.fw.refused("add", "--question", "Abschlag", "--claim-id", self.fw.advance, "--author", "user",
                                  "--user-supplied-wording")
        self.assertEqual(message, f"{RELATIVE} holds 200 questions, the most the check keeps fast; remove one with the "
                                  "user before adding another")

    def test_remove_snapshots_and_deletes_exactly_one_question(self) -> None:
        first = self.fw.add(QUESTION, self.fw.cancel)["question"]
        second = self.fw.add("Abschlag berechnen", self.fw.advance)["question"]
        before = (self.fw.wiki.path / RELATIVE).read_bytes()
        report = self.fw.ok("remove", "--question-id", first["question_id"])
        self.assertEqual((report["removed"], report["question"]), (True, first))
        self.assertEqual(self.fw.records(), [second])
        snapshot = self.fw.wiki.path / report["snapshot"]
        self.assertEqual((snapshot / RELATIVE).read_bytes(), before)
        self.assertEqual(json.loads((snapshot / "snapshot.json").read_text(encoding="utf-8"))["operation"], "findability-remove")
        plan_file = self.fw.wiki.root / "restore-plan.json"
        self.fw.wiki.locked("restore_wiki.py", "plan", "--snapshot-id", Path(report["snapshot"]).name,
                            "--paths-json", json.dumps([RELATIVE]), "--output", str(plan_file))
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        self.fw.wiki.locked("restore_wiki.py", "apply", "--plan-file", str(plan_file),
                            "--expect-plan-sha256", plan["plan_sha256"], "--confirm-restore")
        self.assertEqual((self.fw.wiki.path / RELATIVE).read_bytes(), before)
        self.assertEqual(self.fw.refused("remove", "--question-id", "fq-0000000000000000"),
                         "no findability question fq-0000000000000000")

    def test_an_invalid_line_stops_add_and_check_with_its_line_number(self) -> None:
        good = self.fw.add(QUESTION, self.fw.cancel)["question"]
        path = self.fw.wiki.path / RELATIVE
        lines = {
            "{not json": "invalid JSON",
            json.dumps({**good, "format": "x"}): "unsupported record format",
            json.dumps({**good, "question_id": "fq-1111111111111111", "extra": 1}): "unknown key 'extra'",
            json.dumps(good): "invalid or duplicate question_id",
            json.dumps({**good, "question_id": "fq-2222222222222222", "question": ""}): "invalid question",
            json.dumps({**good, "question_id": "fq-2222222222222222", "claim_id": "clm-1"}): "invalid claim_id",
            json.dumps({**good, "question_id": "fq-2222222222222222", "author": "agent"}): "invalid author",
            json.dumps({**good, "question_id": "fq-2222222222222222", "added_at": "gestern"}): "invalid added_at",
            json.dumps({**good, "question_id": "fq-2222222222222222", "note": "a\nb"}): "invalid note",
        }
        original = path.read_text(encoding="utf-8")
        for line, problem in lines.items():
            with self.subTest(problem=problem):
                path.write_text(original + "\n" + line + "\n", encoding="utf-8")
                self.assertEqual(self.fw.refused("check"), f"{RELATIVE}:3: {problem}")
                self.assertTrue(self.fw.refused("add", "--question", "Abschlag", "--claim-id", self.fw.advance,
                                                "--author", "user", "--user-supplied-wording").startswith(f"{RELATIVE}:3: "))

    def test_a_byte_order_mark_and_crlf_from_a_manual_merge_are_read(self) -> None:
        """Regression: a file merged by hand on Windows (BOM + CRLF) stopped every subcommand with "invalid JSON"."""
        good = self.fw.add(QUESTION, self.fw.cancel)["question"]
        path = self.fw.wiki.path / RELATIVE
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(findability_questions.read_questions(self.fw.wiki.path), [good])
        self.assertEqual(self.fw.ok("check")["questions"], 1)
        second = self.fw.add("Abschlag", self.fw.advance)["question"]
        # The helper writes the file back without a byte order mark.
        self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(self.fw.records(), [good, second])

    def test_a_conflict_copy_of_the_questions_file_stops_the_helper(self) -> None:
        self.fw.add(QUESTION, self.fw.cancel)
        history = self.fw.wiki.path / "meta/history/manual/findability-questions-DESKTOP-AB12C.jsonl"
        history.parent.mkdir(parents=True, exist_ok=True)
        history.write_text("", encoding="utf-8")
        self.assertEqual(self.fw.ok("check")["questions"], 1)
        copy = self.fw.wiki.path / "meta/findability-questions-DESKTOP-AB12C.jsonl"
        copy.write_text("", encoding="utf-8")
        try:
            message = self.fw.refused("check")
            self.assertEqual(
                message,
                f"{RELATIVE} has a synchronization conflict copy (meta/{copy.name}); merge the two files with the "
                "user before recording or checking questions",
            )
            self.assertTrue(self.fw.refused("add", "--question", "Abschlag", "--claim-id", self.fw.advance, "--author",
                                            "user", "--user-supplied-wording").startswith(f"{RELATIVE} has a synchronization"))
        finally:
            copy.unlink()


class Checking(unittest.TestCase):
    def test_check_reports_each_status(self) -> None:
        with TempWiki() as wiki:
            fw = FindabilityWiki(wiki)
            empty = fw.ok("check")
            self.assertEqual((empty["questions"], empty["results"]), (0, []))
            self.assertEqual(set(empty["summary"].values()), {0})
            found = fw.add(QUESTION, fw.cancel)["question"]
            page_only = fw.add("Frist kündigen", fw.address)["question"]
            not_found = fw.add("Wärmepumpe Förderprogramm", fw.advance)["question"]
            missing = fw.add("Schlussrechnung", fw.spare)["question"]
            inactive = fw.add("Abschlag Vorjahresverbrauch", fw.advance)["question"]
            wiki.write("wiki/topics/umzug.md", fw.umzug(with_spare=False))
            wiki.write("wiki/topics/abschlag.md", fw.abschlag(advance_status="superseded"))
            report = fw.ok("check")
            statuses = {item["question_id"]: item for item in report["results"]}
            self.assertEqual(statuses[found["question_id"]]["status"], "found")
            self.assertTrue(statuses[found["question_id"]]["claim_returned"])
            self.assertEqual(statuses[found["question_id"]]["page"], "wiki/topics/umzug.md")
            self.assertEqual(statuses[page_only["question_id"]]["status"], "found_page_only")
            self.assertEqual(statuses[not_found["question_id"]]["status"], "target_inactive")
            self.assertEqual(statuses[missing["question_id"]]["status"], "target_missing")
            self.assertIsNone(statuses[missing["question_id"]]["page"])
            self.assertIsNone(statuses[missing["question_id"]]["page_rank"])
            self.assertEqual(statuses[inactive["question_id"]]["status"], "target_inactive")
            wiki.write("wiki/topics/abschlag.md", fw.abschlag())
            report = fw.ok("check")
            statuses = {item["question_id"]: item for item in report["results"]}
            self.assertEqual(statuses[not_found["question_id"]]["status"], "not_found")
            self.assertIsNone(statuses[not_found["question_id"]]["page_rank"])
            self.assertEqual(report["summary"], {"found": 2, "found_page_only": 1, "not_found": 1,
                                                 "target_missing": 1, "target_inactive": 0})
            self.assertEqual([item["question_id"] for item in report["results"]],
                             [found["question_id"], page_only["question_id"], not_found["question_id"],
                              missing["question_id"], inactive["question_id"]])
            self.assertEqual(report["last_release"]["version"], wiki.current_version())
            self.assertEqual(report["limit"], 12)
            self.assertEqual(fw.refused("check", "--limit", "0"), "limit must be between 1 and 100")

    QUESTIONS = (QUESTION, "Abschlag Vorjahresverbrauch", "Frist kündigen")

    def check_in_process(self, wiki: Wiki, fw: FindabilityWiki) -> tuple[dict[str, Any], int]:
        """Record three questions, then run `check` in this process: the report and how often the wiki was loaded."""
        for question, claim_id in zip(self.QUESTIONS, (fw.cancel, fw.advance, fw.address)):
            fw.add(question, claim_id)
        token_file = wiki.root / "check-token"
        wiki.maintain("wiki_lock.py", "acquire", "--target", str(wiki.path), "--token-file", str(token_file),
                      "--owner", "test/harness")
        try:
            argv = ["findability_questions.py", "check", "--target", str(wiki.path), "--lock-token",
                    token_file.read_text(encoding="utf-8").strip()]
            output = io.StringIO()
            core = findability_questions.search_core
            with mock.patch.object(sys, "argv", argv), mock.patch.object(core, "load", wraps=core.load) as loads, \
                    contextlib.redirect_stdout(output):
                self.assertEqual(findability_questions.main(), 0)
        finally:
            wiki.maintain("wiki_lock.py", "release", "--target", str(wiki.path), "--token-file", str(token_file),
                          check=False)
        return json.loads(output.getvalue()), loads.call_count

    def test_check_ranks_like_the_query_skill(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "query-llm-wiki" / "scripts"))
        import search_core  # byte-identical in both skills (SharedModuleParity)

        with TempWiki() as wiki:
            report, _ = self.check_in_process(wiki, FindabilityWiki(wiki))
            self.assertEqual([item["question"] for item in report["results"]], list(self.QUESTIONS))
            for item in report["results"]:
                with self.subTest(question=item["question"]):
                    paths = [result["path"] for result in search_core.search(wiki.path, item["question"], limit=100)["results"]]
                    self.assertEqual(item["page_rank"], paths.index(item["page"]) + 1)
                    self.assertEqual(item["first_result"], paths[0])

    def test_check_loads_the_wiki_once(self) -> None:
        with TempWiki() as wiki:
            report, loads = self.check_in_process(wiki, FindabilityWiki(wiki))
            self.assertEqual(report["questions"], 3)
            self.assertEqual(loads, 1)

    def test_the_questions_never_enter_a_release_or_an_export(self) -> None:
        with TempWiki() as wiki:
            fw = FindabilityWiki(wiki)
            fw.add(QUESTION, fw.cancel)
            wiki.release("findability-after")
            manifest = json.loads(wiki.read("meta/manifest.json"))
            self.assertNotIn(RELATIVE, [entry["path"] for entry in manifest["files"]])
            self.assertEqual(wiki.verify(query_side=True)["state"], "ready")
            lint = json.loads(wiki.lint().stdout)
            self.assertTrue(lint["valid"], lint["errors"])
            with tempfile.TemporaryDirectory() as output:
                exported = subprocess.run(
                    [sys.executable, "-B", str(MAINTAIN / "export_wiki_skill.py"), "--target", str(wiki.path),
                     "--output-dir", output, "--skill-name", "findability-probe"],
                    capture_output=True, encoding="utf-8", cwd=str(MAINTAIN),
                )
                self.assertEqual(exported.returncode, 0, exported.stderr)
                shipped = [path.relative_to(output).as_posix() for path in Path(output).rglob("*")]
                self.assertTrue(shipped)
                self.assertFalse([path for path in shipped if "findability" in path.split("/")[-1] and path.endswith(".jsonl")])
                for package in Path(output).glob("*.skill"):
                    with zipfile.ZipFile(package) as archive:
                        self.assertFalse([name for name in archive.namelist() if "findability-questions" in name])

    def test_the_report_is_deterministic(self) -> None:
        with TempWiki() as wiki:
            fw = FindabilityWiki(wiki)
            fw.add(QUESTION, fw.cancel)
            fw.add("Abschlag Vorjahresverbrauch", fw.advance)
            first, second = fw.ok("check"), fw.ok("check")
            self.assertIsInstance(first.pop("elapsed_ms"), int)
            second.pop("elapsed_ms")
            self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
            self.assertEqual(first["boundary"], findability_questions.BOUNDARY)


if __name__ == "__main__":
    unittest.main()
