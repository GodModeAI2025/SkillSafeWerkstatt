#!/usr/bin/env python3
"""Reformulations in one call (Stufe 3): request parsing, planning, fusion, command line.

The search is lexical, so the agent supplies synonyms, the wiki's own terms or
a translation as up to four reformulations (`--also`, or `--request -` with one
JSON object on standard input). One call reads the release once and ranks the
question and every reformulation over it. These tests pin the contract:

- the question's `results`, `coverage` and `facets` are exactly those of a
  search without reformulations; each result only gains `found_by`;
- pages that only reformulations return within the limit come back in
  `reformulation_results`, taken in turn by rank, deduplicated, without
  navigation pages, capped by the same limit;
- `coverage.formulations` counts per search and `coverage.reformulation_results`
  counts the block, in every report;
- invalid input exits 1 with one line on standard error and nothing on standard
  output, usage errors exit 2, and every file is read once per call.

Core tests use invented rock names (quarzit, basalt, granit, gneis) so that no
word-form heuristic interferes; command-line tests run on a released harness
wiki.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "query-llm-wiki" / "scripts"))

import search_core  # noqa: E402
from harness import QUERY, REPO, TempWiki  # noqa: E402
from test_search_coverage import assert_reformulation_identities, build_coverage_wiki  # noqa: E402
from wiki_filters import validate_selector  # noqa: E402

INVALID = "request is invalid: "
NOT_UTF8 = INVALID + "not UTF-8 text; send UTF-8, or escape every non-ASCII character as \\uXXXX"
SURROGATE = "holds a lone surrogate escape; write a character outside U+FFFF as a surrogate pair, or as UTF-8"
NEW_COVERAGE_KEYS = ("formulations", "reformulation_results")
NEW_TOP_KEYS = ("formulations", "dropped_formulations", "reformulation_results")


def page(title: str, body: str, kind: str = "concept") -> str:
    return "\n".join(["---", f'title: "{title}"', 'status: "active"', f'type: "{kind}"', "---", "", body, ""])


def filler(count: int) -> str:
    """Words that match none of the rock names, to lengthen a body."""
    words = ("Feldspat", "Glimmer", "Kalkstein", "Dolomit", "Schiefer", "Mergel")
    return " ".join(words[number % len(words)] for number in range(count))


class Tree:
    """A folder the search core can read: WIKI.md, an index, and the given pages."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def __enter__(self) -> Path:
        self._directory = tempfile.TemporaryDirectory(prefix="lmwiki-formulations-")
        root = Path(self._directory.name)
        files = {"WIKI.md": "# Wiki\n", "wiki/index.md": page("Index", "Startseite.", "index"), **self.pages}
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    def __exit__(self, *_exc: object) -> None:
        self._directory.cleanup()


#: Section 2.4 of the spec: F1 "quarzit" ranks a, b, c; F2 "basalt" ranks d, a, e; "zirkon" matches nothing.
WORKED_EXAMPLE = {
    "wiki/a.md": page("Quarzit", "Quarzit. Basalt."),
    "wiki/b.md": page("Lager", "Quarzit " + filler(4)),
    "wiki/c.md": page("Halde", "Quarzit " + filler(30)),
    "wiki/d.md": page("Basalt", "Basalt."),
    "wiki/e.md": page("Bruch", "Basalt " + filler(30)),
}


def paths(items: list[dict]) -> list[str]:
    return [item["path"] for item in items]


def without_new_keys(report: dict) -> dict:
    report = {key: value for key, value in report.items() if key not in NEW_TOP_KEYS}
    report["coverage"] = {key: value for key, value in report["coverage"].items() if key not in NEW_COVERAGE_KEYS}
    report["results"] = [{key: value for key, value in item.items() if key != "found_by"} for item in report["results"]]
    return report


class FakeStream:
    def __init__(self, data: bytes = b"", tty: bool = False) -> None:
        self.buffer = io.BytesIO(data)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class RequestParsing(unittest.TestCase):
    """Pure decoding and shape checks of `--request -`."""

    def test_a_utf8_request_with_bom_reads_like_one_without(self) -> None:
        plain = b'{"query": "Zahlerstand", "also": ["Ablesung"]}'
        self.assertEqual(search_core.read_request(b"\xef\xbb\xbf" + plain), search_core.read_request(plain))
        self.assertEqual(
            search_core.read_request(plain), {"query": "Zahlerstand", "also": ["Ablesung"], "filter": None}
        )

    def test_utf16_requests_with_and_without_bom_are_decoded(self) -> None:
        text = '{"query": "Zählerstand", "also": ["Kündigung"]}'
        expected = {"query": "Zählerstand", "also": ["Kündigung"], "filter": None}
        for label, raw in (
            ("FF FE", b"\xff\xfe" + text.encode("utf-16-le")),
            ("FE FF", b"\xfe\xff" + text.encode("utf-16-be")),
            ("little endian without BOM", text.encode("utf-16-le")),
            ("big endian without BOM", text.encode("utf-16-be")),
        ):
            with self.subTest(encoding=label):
                self.assertEqual(search_core.read_request(raw), expected)

    def test_unicode_escapes_carry_non_ascii_through_an_ascii_pipe(self) -> None:
        raw = b'{"query": "K\\u00fcndigung", "also": ["Vertrag k\\u00fcndigen", "Ehepartner\\u0027s Vertrag"]}'
        self.assertTrue(raw.isascii())
        request = search_core.read_request(raw)
        self.assertEqual(request["query"], "Kündigung")
        self.assertEqual(request["also"], ["Vertrag kündigen", "Ehepartner's Vertrag"])

    def test_non_utf8_bytes_are_refused_with_the_escape_hint(self) -> None:
        with self.assertRaises(search_core.RequestError) as caught:
            search_core.read_request('{"query": "Kündigung"}'.encode("cp1252"))
        self.assertEqual(str(caught.exception), NOT_UTF8)

    def test_text_re_encoded_on_the_way_is_refused(self) -> None:
        hint = "looks re-encoded on the way (a ? before a letter, or U+FFFD); escape every non-ASCII character as \\uXXXX"
        for raw, field in (
            (b'{"query": "K?ndigung"}', "query"),
            (b'{"query": "x", "also": ["ok", "Z\\ufffdhler"]}', "also[1]"),
            # Windows PowerShell 5.1 with an ASCII output encoding: a word-initial
            # umlaut, two umlauts in a row, and mangled German quotation marks.
            ('{"query": "Ökostrom"}'.encode("ascii", "replace"), "query"),
            ('{"query": "x", "also": ["Überweisung Abschlag"]}'.encode("ascii", "replace"), "also[0]"),
            ('{"query": "Grüße"}'.encode("ascii", "replace"), "query"),
            ('{"query": "„Abschlag“"}'.encode("ascii", "replace"), "query"),
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(search_core.RequestError) as caught:
                    search_core.read_request(raw)
                self.assertEqual(str(caught.exception), f"{INVALID}{field} {hint}")
        self.assertEqual(search_core.read_request(b'{"query": "K\\u00fcndigung?"}')["query"], "Kündigung?")
        self.assertEqual(search_core.read_request(b'{"query": "Was gilt? Wann?"}')["query"], "Was gilt? Wann?")
        self.assertEqual(search_core.read_request(b'{"query": "\\u00a7 19?"}')["query"], "§ 19?")
        self.assertEqual(search_core.read_request(b'{"query": "\\u00d6kostrom"}')["query"], "Ökostrom")

    def test_shape_errors_name_the_offending_key(self) -> None:
        cases = {
            b'["query"]': "the top level must be a JSON object",
            b'{"query": "x", "limit": 3}': "unknown key 'limit'; allowed keys are query, also, filter",
            b'{"also": ["x"]}': "query must be a non-empty string",
            b'{"query": "   "}': "query must be a non-empty string",
            b'{"query": 5}': "query must be a non-empty string",
            b'{"query": "x", "also": "y"}': "also must be a list of strings",
            b'{"query": "x", "also": ["y", 3]}': "also[1] must be a string",
            b'{"query": "x", "filter": "all"}': "filter must be a JSON object (a selector)",
            b'{"query": "x", "query": "y"}': "duplicate key 'query'",
            b'{"query": "x", "filter": {"kind": "all", "kind": "paths"}}': "duplicate key 'kind'",
            b'{"query": "x", "also": [NaN]}': "NaN and Infinity are not JSON",
            b'{"query": Infinity}': "NaN and Infinity are not JSON",
            b"": "empty input; pipe one JSON object to --request -",
            b"\xef\xbb\xbf \r\n": "empty input; pipe one JSON object to --request -",
            b'{"query": }': "not valid JSON: Expecting value (line 1 column 11)",
            # Half a character outside U+FFFF passes JSON but no UTF-8 output.
            b'{"query": "Z\\ud800hlerstand"}': f"query {SURROGATE}",
            b'{"query": "x", "also": ["Ablesung \\udcff"]}': f"also[0] {SURROGATE}",
            b'{"query": "x", "filter": {"kind": "paths", "paths": ["wiki/\\udc80.md"]}}': f"filter {SURROGATE}",
            b'{"query": "x"}' + b" " * (search_core.MAX_REQUEST_BYTES - 13): "request exceeds 65536 bytes",
        }
        for raw, detail in cases.items():
            with self.subTest(raw=raw[:40]):
                with self.assertRaises(search_core.RequestError) as caught:
                    search_core.read_request(raw)
                self.assertEqual(str(caught.exception), INVALID + detail)
        at_the_cap = b'{"query": "x"}' + b" " * (search_core.MAX_REQUEST_BYTES - 14)
        self.assertEqual(len(at_the_cap), search_core.MAX_REQUEST_BYTES)
        self.assertEqual(search_core.read_request(at_the_cap)["query"], "x")
        self.assertEqual(search_core.read_request(b'{"query": "\\ud83d\\ude00"}')["query"], "\U0001f600")

    def test_a_missing_or_terminal_stdin_is_refused(self) -> None:
        message = INVALID + "--request - reads one JSON object from standard input, but standard input is a terminal or closed"
        for stream in (None, FakeStream(b'{"query": "x"}', tty=True), io.StringIO('{"query": "x"}')):
            with self.subTest(stream=type(stream).__name__):
                with self.assertRaises(search_core.RequestError) as caught:
                    search_core.request_from_stdin(stream)
                self.assertEqual(str(caught.exception), message)
        self.assertEqual(search_core.request_from_stdin(FakeStream(b'{"query": "x"}'))["query"], "x")

    def test_the_reader_takes_at_most_one_byte_beyond_the_cap(self) -> None:
        stream = FakeStream(b"{" + b" " * (2 * search_core.MAX_REQUEST_BYTES))
        with self.assertRaises(search_core.RequestError):
            search_core.request_from_stdin(stream)
        self.assertEqual(stream.buffer.tell(), search_core.MAX_REQUEST_BYTES + 1)


class FormulationPlanning(unittest.TestCase):
    def test_at_most_four_reformulations_and_200_characters(self) -> None:
        kept, dropped = search_core.plan_formulations("Frage", ["a1", "b2", "c3", "d4"])
        self.assertEqual((len(kept), dropped), (5, []))
        with self.assertRaises(search_core.RequestError) as caught:
            search_core.plan_formulations("Frage", ["a1", "b2", "c3", "d4", ""])
        self.assertEqual(
            str(caught.exception),
            "reformulations are invalid: at most 4 reformulations may be given (5 searches including the query); got 5",
        )
        longest = "  " + "x" * 200 + "  "
        kept, _ = search_core.plan_formulations("Frage", [longest])
        self.assertEqual(kept[1]["text"], "x" * 200, "the length counts after stripping")
        with self.assertRaises(search_core.RequestError) as caught:
            search_core.plan_formulations("Frage", ["ok", "y" * 201])
        self.assertEqual(
            str(caught.exception), "reformulations are invalid: reformulation 2 is longer than 200 characters (201)"
        )
        # The query itself is never refused for its length.
        self.assertEqual(search_core.plan_formulations("q" * 5000, [])[0][0]["text"], "q" * 5000)

    def test_duplicates_are_detected_after_case_accent_and_punctuation_folding(self) -> None:
        kept, dropped = search_core.plan_formulations(
            "Kündigung Frist?", ["Kündigung, Frist", "Laufzeit", "KUNDIGUNG frist!", "laufzeit."]
        )
        self.assertEqual([item["text"] for item in kept], ["Kündigung Frist?", "Laufzeit"])
        self.assertEqual(dropped, [
            {"position": 1, "text": "Kündigung, Frist", "reason": "duplicate", "duplicate_of": 0},
            {"position": 3, "text": "KUNDIGUNG frist!", "reason": "duplicate", "duplicate_of": 0},
            {"position": 4, "text": "laufzeit.", "reason": "duplicate", "duplicate_of": 1},
        ])

    def test_word_order_and_ae_spelling_keep_formulations_apart(self) -> None:
        kept, dropped = search_core.plan_formulations("Frist Kündigung", ["Kündigung Frist", "Kuendigung Frist"])
        self.assertEqual(dropped, [])
        self.assertEqual(len(kept), 3)
        self.assertNotEqual(search_core.formulation_key("Kuendigung"), search_core.formulation_key("Kündigung"))
        self.assertEqual(search_core.formulation_key("  Kündigung,  FRIST! "), "kundigung frist")

    def test_empty_and_wordless_reformulations_are_dropped_not_refused(self) -> None:
        kept, dropped = search_core.plan_formulations("Frage", ["", "  ", "?!"])
        self.assertEqual(kept, [{"index": 0, "text": "Frage", "origin": "query"}])
        self.assertEqual(dropped, [
            {"position": 1, "text": "", "reason": "empty", "duplicate_of": None},
            {"position": 2, "text": "", "reason": "empty", "duplicate_of": None},
            {"position": 3, "text": "?!", "reason": "empty", "duplicate_of": None},
        ])

    def test_indices_are_consecutive_and_positions_name_the_given_place(self) -> None:
        kept, dropped = search_core.plan_formulations("Frage", ["", "Basalt", "frage", "Granit"])
        self.assertEqual(
            kept,
            [
                {"index": 0, "text": "Frage", "origin": "query"},
                {"index": 1, "text": "Basalt", "origin": "also"},
                {"index": 2, "text": "Granit", "origin": "also"},
            ],
        )
        self.assertEqual([item["position"] for item in dropped], [1, 3])


class Fusion(unittest.TestCase):
    """The core: the question's ranking is untouched, reformulation-only pages come back apart."""

    def test_results_are_identical_with_and_without_reformulations(self) -> None:
        pages = {**WORKED_EXAMPLE, "wiki/f.md": page("Zirkon", "Zirkon und Quarzit.")}
        with Tree(pages) as root:
            for limit in (1, 2, 12):
                with self.subTest(limit=limit):
                    plain = search_core.search(root, "Zirkon Quarzit", limit=limit)
                    fused = search_core.search(root, "Zirkon Quarzit", also=["Basalt", "Quarzit"], limit=limit)
                    self.assertEqual(without_new_keys(fused), without_new_keys(plain))
                    self.assertEqual(fused["facets"], plain["facets"])
                    self.assertEqual(fused["matched_concepts"], plain["matched_concepts"])
                    self.assertEqual(fused["expanded_terms"], plain["expanded_terms"])

    def test_found_by_names_every_search_and_its_rank(self) -> None:
        with Tree(WORKED_EXAMPLE) as root:
            report = search_core.search(root, "Quarzit", also=["Basalt", "Quarzit Basalt"], limit=12)
            basalt = search_core.search(root, "Basalt", limit=12)
            both = search_core.search(root, "Quarzit Basalt", limit=12)
        rank_in = lambda found, path: paths(found["results"]).index(path) + 1  # noqa: E731
        for number, item in enumerate(report["results"], 1):
            with self.subTest(path=item["path"]):
                self.assertEqual(item["found_by"][0], {"formulation": 0, "rank": number})
                expected = [{"formulation": 0, "rank": number}]
                for index, found in ((1, basalt), (2, both)):
                    if item["path"] in paths(found["results"]):
                        expected.append({"formulation": index, "rank": rank_in(found, item["path"])})
                self.assertEqual(item["found_by"], expected)
        self.assertEqual(paths(report["reformulation_results"]), ["wiki/d.md", "wiki/e.md"])

    def test_reformulation_results_interleave_by_rank_round_robin(self) -> None:
        with Tree(WORKED_EXAMPLE) as root:
            self.assertEqual(paths(search_core.search(root, "Quarzit")["results"]), ["wiki/a.md", "wiki/b.md", "wiki/c.md"])
            self.assertEqual(paths(search_core.search(root, "Basalt")["results"]), ["wiki/d.md", "wiki/a.md", "wiki/e.md"])
            report = search_core.search(root, "Zirkon", also=["Quarzit", "Basalt"], limit=5)
            quarzit = search_core.search(root, "Quarzit", limit=5)
        self.assertEqual(report["results"], [])
        block = report["reformulation_results"]
        self.assertEqual(paths(block), ["wiki/a.md", "wiki/d.md", "wiki/b.md", "wiki/c.md", "wiki/e.md"])
        self.assertEqual([item["via"] for item in block], [1, 2, 1, 1, 2])
        self.assertEqual(block[0]["found_by"], [{"formulation": 1, "rank": 1}, {"formulation": 2, "rank": 2}])
        self.assertEqual(block[1]["found_by"], [{"formulation": 2, "rank": 1}])
        # Score, snippet, claims and matched terms come from the formulation in `via`.
        expected = {key: value for key, value in quarzit["results"][0].items() if key != "found_by"}
        self.assertEqual({key: value for key, value in block[0].items() if key not in ("found_by", "via")}, expected)
        self.assertEqual(list(block[0])[-2:], ["found_by", "via"])
        coverage = report["coverage"]["reformulation_results"]
        self.assertEqual((coverage["returned"], coverage["candidates"], coverage["truncated"]), (5, 5, False))

    def test_reformulation_results_exclude_results_and_navigation_pages(self) -> None:
        pages = {
            **WORKED_EXAMPLE,
            "wiki/index.md": page("Index", "Quarzit Quarzit Quarzit Basalt Basalt Basalt", "index"),
            "wiki/b.md": page("Lager", "Quarzit Glimmer " + filler(4)),
        }
        with Tree(pages) as root:
            report = search_core.search(root, "Glimmer Lager", also=["Quarzit", "Basalt"], limit=3)
            quarzit = search_core.search(root, "Quarzit", limit=3)
        self.assertIn("wiki/index.md", paths(quarzit["results"]))
        self.assertEqual(report["results"][0]["path"], "wiki/b.md")
        block = paths(report["reformulation_results"])
        self.assertNotIn("wiki/index.md", block)
        self.assertTrue(set(block).isdisjoint(paths(report["results"])))
        self.assertTrue(all(not item["navigation"] for item in report["reformulation_results"]))
        self.assertEqual(report["coverage"]["reformulation_results"]["navigation_skipped"], 1)
        assert_reformulation_identities(self, report, limit=3)

    def test_a_page_the_question_ranks_below_the_limit_shows_its_rank_from_formulation_0(self) -> None:
        pages = {
            **{f"wiki/g{number}.md": page(f"Glimmer {number}", "Glimmer " * (5 - number)) for number in range(1, 5)},
            "wiki/a.md": page("Quarzit", "Quarzit. Glimmer " + filler(60)),
        }
        with Tree(pages) as root:
            question = search_core.search(root, "Glimmer", limit=12)
            report = search_core.search(root, "Glimmer", also=["Quarzit"], limit=2)
        below = paths(question["results"]).index("wiki/a.md") + 1
        self.assertGreater(below, 2)
        entry = report["reformulation_results"][0]
        self.assertEqual(entry["path"], "wiki/a.md")
        self.assertEqual(entry["found_by"], [{"formulation": 0, "rank": below}, {"formulation": 1, "rank": 1}])
        self.assertEqual(report["coverage"]["formulations"][0]["contributed"], 0)
        self.assertEqual(report["coverage"]["formulations"][1]["contributed"], 1)

    def test_the_block_has_its_own_limit_and_counts_what_it_omits(self) -> None:
        rocks = ("granit", "basalt", "quarzit", "gneis")
        pages = {
            f"wiki/{rock}-{number}.md": page(f"Fund {rock} {number}", f"{rock.capitalize()} " + filler(number * 3))
            for rock in rocks
            for number in range(1, 10)
        }
        with Tree(pages) as root:
            report = search_core.search(root, "Zirkon", also=[rock.capitalize() for rock in rocks], limit=8)
        coverage = report["coverage"]["reformulation_results"]
        self.assertEqual(coverage["candidates"], 32, "every reformulation feeds only its own top 8")
        self.assertEqual(coverage["returned"], 8)
        self.assertEqual(coverage["returned"] + coverage["omitted_count"], coverage["candidates"])
        self.assertTrue(coverage["truncated"])
        expected = [(f"wiki/{rock}-{number}.md", index, number) for number in range(1, 9) for index, rock in enumerate(rocks, 1)]
        self.assertEqual([(item["path"], item["via"], item["found_by"][0]["rank"]) for item in report["reformulation_results"]], expected[:8])
        self.assertEqual(
            coverage["omitted_top"],
            [{"path": path, "formulation": index, "rank": rank} for path, index, rank in expected[8:28]],
        )
        assert_reformulation_identities(self, report, limit=8)

    def test_coverage_per_formulation_and_its_identities(self) -> None:
        with Tree(WORKED_EXAMPLE) as root:
            report = search_core.search(root, "Quarzit", also=["Basalt", "Obsidian"], limit=2)
            basalt = search_core.search(root, "Basalt", limit=2)
        formulations = report["coverage"]["formulations"]
        self.assertEqual(len(formulations), 3)
        top = report["coverage"]
        self.assertEqual(
            {key: formulations[0][key] for key in ("matched", "within_limit", "truncated")},
            {"matched": top["matched"], "within_limit": top["returned"], "truncated": top["truncated"]},
        )
        self.assertEqual(formulations[1]["matched"], basalt["coverage"]["matched"])
        self.assertEqual(formulations[1]["within_limit"], 2)
        self.assertTrue(formulations[1]["truncated"])
        self.assertEqual(formulations[1]["unmatched_terms"], [])
        self.assertEqual(
            formulations[1]["query_terms"],
            [{key: value for key, value in item.items() if key != "forms"} for item in basalt["coverage"]["query_terms"]],
        )
        nothing = formulations[2]
        self.assertEqual((nothing["matched"], nothing["within_limit"], nothing["truncated"], nothing["contributed"]), (0, 0, False, 0))
        self.assertEqual(nothing["unmatched_terms"], ["obsidian"])
        self.assertEqual(
            list(nothing),
            [
                "formulation", "matched", "within_limit", "truncated", "contributed", "query_terms", "dropped_terms",
                "unmatched_terms", "form_only_terms", "terms_only_in_unsearched",
            ],
        )
        self.assertEqual([item["text"] for item in report["formulations"]], ["Quarzit", "Basalt", "Obsidian"])
        assert_reformulation_identities(self, report, limit=2)

    def test_a_call_without_reformulations_has_the_uniform_shape(self) -> None:
        with Tree(WORKED_EXAMPLE) as root:
            report = search_core.search(root, "Quarzit", also=["quarzit!"], limit=12)
        self.assertEqual(report["coverage"]["format"], "lmwiki-search-coverage/3")
        self.assertEqual(search_core.COVERAGE_FORMAT, "lmwiki-search-coverage/3")
        self.assertEqual(
            report["formulations"],
            [{"index": 0, "text": "Quarzit", "origin": "query", "matched_concepts": [], "expanded_terms": []}],
        )
        self.assertEqual(
            report["dropped_formulations"],
            [{"position": 1, "text": "quarzit!", "reason": "duplicate", "duplicate_of": 0}],
        )
        self.assertEqual(report["reformulation_results"], [])
        self.assertEqual(len(report["coverage"]["formulations"]), 1)
        self.assertEqual(list(report["coverage"])[-2:], ["formulations", "reformulation_results"])
        self.assertEqual(
            list(report),
            [
                "searched_files", "filtered_out", "formulations", "dropped_formulations", "matched_concepts",
                "expanded_terms", "facets", "results", "reformulation_results", "coverage", "parser_errors",
            ],
        )
        self.assertEqual(list(report["results"][0])[-1], "found_by")
        assert_reformulation_identities(self, report, limit=12)

    def test_every_file_is_read_once_whatever_the_number_of_formulations(self) -> None:
        pages = {**WORKED_EXAMPLE, "sources/quelle.md": page("Quelle", "Basalt und Gneis", "source")}
        counts = []
        with Tree(pages) as root:
            for also in ([], ["Basalt", "Granit", "Gneis", "Quarzit Basalt"]):
                with mock.patch.object(search_core, "read_document", wraps=search_core.read_document) as reader:
                    search_core.search(root, "Quarzit", also=also, limit=12)
                counts.append(reader.call_count)
        # WIKI.md, the index and five pages are searched; the source is counted.
        self.assertEqual(counts, [8, 8])

    def test_selector_and_scopes_apply_to_every_formulation(self) -> None:
        pages = {**WORKED_EXAMPLE, "sources/quelle.md": page("Quelle", "Basalt Basalt Basalt", "source")}
        selector = validate_selector({"kind": "paths", "paths": ["wiki/a.md", "wiki/b.md", "wiki/d.md", "sources/quelle.md"]})
        with Tree(pages) as root:
            narrowed = search_core.search(root, "Zirkon", also=["Quarzit", "Basalt"], limit=12, selector=selector)
            plain = search_core.search(root, "Zirkon", also=["Basalt"], limit=12)
            with_sources = search_core.search(root, "Zirkon", also=["Basalt"], limit=12, include_sources=True)
        allowed = set(selector["paths"])
        self.assertTrue(narrowed["reformulation_results"])
        self.assertTrue(set(paths(narrowed["reformulation_results"])) <= allowed)
        self.assertNotIn("sources/quelle.md", paths(plain["reformulation_results"]))
        self.assertIn("sources/quelle.md", paths(with_sources["reformulation_results"]))
        self.assertEqual(plain["coverage"]["formulations"][1]["terms_only_in_unsearched"], {"sources": []})

    def test_also_errors_raise_request_error_from_the_core(self) -> None:
        with Tree(WORKED_EXAMPLE) as root:
            with self.assertRaises(search_core.RequestError):
                search_core.search(root, "Quarzit", also=["a"] * 5)
            with self.assertRaises(search_core.RequestError):
                search_core.search(root, "Quarzit", also=["x" * 201])
            with self.assertRaises(search_core.QueryError):
                search_core.search(root, "?!", also=["Basalt"])
        self.assertTrue(issubclass(search_core.RequestError, ValueError))


class CommandLine(unittest.TestCase):
    """The query skill's wrapper on a released wiki."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._context = TempWiki()
        cls.wiki = cls._context.__enter__()
        build_coverage_wiki(cls.wiki)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._context.__exit__(None, None, None)

    def cli(self, *arguments: str, stdin: bytes = b"", **environment: str) -> subprocess.CompletedProcess:
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", **environment})
        return subprocess.run(
            [sys.executable, "-B", str(QUERY / "search_wiki.py"), "--target", str(self.wiki.path), *arguments],
            input=stdin,
            capture_output=True,
            env=env,
        )

    def report(self, *arguments: str, stdin: bytes = b"", **environment: str) -> dict:
        result = self.cli(*arguments, stdin=stdin, **environment)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return json.loads(result.stdout.decode("utf-8"))

    def assert_refused(self, result: subprocess.CompletedProcess, code: int, message: str) -> None:
        self.assertEqual(result.returncode, code, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stdout, b"")
        self.assertIn(message, result.stderr.decode("utf-8"))

    def test_also_on_the_command_line_equals_the_core(self) -> None:
        report = self.report("--query", "Ablesung", "--also", "Messpunkt", "--also", "Zählerstand", "--limit", "5")
        core = search_core.search(self.wiki.path, "Ablesung", also=["Messpunkt", "Zählerstand"], limit=5)
        for key in ("formulations", "dropped_formulations", "results", "reformulation_results", "coverage", "facets"):
            self.assertEqual(report[key], core[key], key)
        self.assertTrue(report["reformulation_results"])
        self.assertEqual(
            list(report)[:5], ["target", "query", "formulations", "dropped_formulations", "release"]
        )
        self.assertEqual(list(report).index("reformulation_results"), list(report).index("results") + 1)
        assert_reformulation_identities(self, report, limit=5)

    def test_a_request_on_stdin_equals_query_and_also(self) -> None:
        request = b'\xef\xbb\xbf{"query": "Ablesung", "also": ["Messpunkt", "Z\\u00e4hlerstand", "ablesung"]}'
        piped = self.report("--request", "-", "--limit", "5", stdin=request)
        flags = self.report(
            "--query", "Ablesung", "--also", "Messpunkt", "--also", "Zählerstand", "--also", "ablesung", "--limit", "5"
        )
        self.assertEqual(piped, flags)
        self.assertEqual(
            piped["dropped_formulations"], [{"position": 3, "text": "ablesung", "reason": "duplicate", "duplicate_of": 0}]
        )

    def test_a_request_filter_replaces_filter_json_and_both_are_refused(self) -> None:
        selector = {"kind": "filter", "conditions": [{"property": "__filename", "operator": "starts_with", "value": "messpunkt-0"}]}
        request = json.dumps({"query": "Messpunkt", "also": ["Netzbetreiber"], "filter": selector}).encode("ascii")
        piped = self.report("--request", "-", "--limit", "100", stdin=request)
        flags = self.report("--query", "Messpunkt", "--also", "Netzbetreiber", "--filter-json", json.dumps(selector), "--limit", "100")
        self.assertEqual(piped, flags)
        self.assertGreater(piped["filtered_out"], 0)
        both = self.cli("--request", "-", "--filter-json", json.dumps(selector), stdin=request)
        self.assert_refused(
            both, 1, "request is invalid: filter is given both in the request and as --filter-json; give it once"
        )
        bad = json.dumps({"query": "Messpunkt", "filter": {"kind": "bogus"}}).encode("ascii")
        self.assert_refused(self.cli("--request", "-", stdin=bad), 1, "request is invalid: filter is not a valid selector: ")

    def test_usage_errors_exit_2_with_nothing_on_stdout(self) -> None:
        request = b'{"query": "Messpunkt"}'
        for arguments, message in (
            (("--query", "Messpunkt", "--request", "-"), "not allowed with argument"),
            ((), "one of the arguments --query --request is required"),
            (("--request", "-", "--also", "Netzbetreiber"), "--also cannot be combined with --request"),
            (("--request", "x.json"), "--request accepts only '-' (standard input)"),
        ):
            with self.subTest(arguments=arguments):
                self.assert_refused(self.cli(*arguments, stdin=request), 2, message)

    def test_invalid_reformulations_exit_1_with_nothing_on_stdout(self) -> None:
        cases = (
            (("--request", "-"), b'{"query": "Messpunkt", "also": [}', "request is invalid: not valid JSON: "),
            (("--query", "Messpunkt", *[item for number in range(5) for item in ("--also", f"w{number}")]), b"",
             "reformulations are invalid: at most 4 reformulations may be given (5 searches including the query); got 5"),
            (("--query", "Messpunkt", "--also", "x" * 201), b"",
             "reformulations are invalid: reformulation 1 is longer than 200 characters (201)"),
            (("--request", "-"), '{"query": "Zählerstand"}'.encode("cp1252"), NOT_UTF8),
            (("--request", "-"), b'{"query": "Messpunkt", "also": ["x"], "limit": 5}',
             "request is invalid: unknown key 'limit'; allowed keys are query, also, filter"),
            (("--request", "-"), b'{"query": "Z\\ud800hlerstand"}', f"request is invalid: query {SURROGATE}"),
            (("--request", "-"), b'{"query": "?kostrom"}', "request is invalid: query looks re-encoded on the way"),
        )
        for arguments, stdin, message in cases:
            with self.subTest(arguments=arguments[:3], stdin=stdin[:30]):
                self.assert_refused(self.cli(*arguments, stdin=stdin), 1, message)

    def test_invalid_input_is_refused_before_the_wiki_is_touched(self) -> None:
        missing = self.wiki.root / "nicht-da"
        result = subprocess.run(
            [sys.executable, "-B", str(QUERY / "search_wiki.py"), "--target", str(missing), "--request", "-"],
            input=b'{"query": ""}',
            capture_output=True,
        )
        self.assert_refused(result, 1, "request is invalid: query must be a non-empty string")

    def test_a_request_survives_a_cp1252_environment(self) -> None:
        request = '{"query": "Zählerstand", "also": ["Ablesung Zählerstände"]}'.encode("utf-8")
        report = self.report("--request", "-", stdin=request, PYTHONIOENCODING="cp1252")
        self.assertEqual(report["query"], "Zählerstand")
        self.assertEqual([item["text"] for item in report["formulations"]], ["Zählerstand", "Ablesung Zählerstände"])
        self.assertTrue(report["results"])

    def test_output_is_deterministic_across_hash_seeds(self) -> None:
        arguments = ("--query", "Messpunkt Zählerstand", "--also", "Netzbetreiber", "--also", "Ablesung", "--limit", "3")
        outputs = {self.cli(*arguments, PYTHONHASHSEED=seed).stdout for seed in ("0", "1")}
        self.assertEqual(len(outputs), 1)
        self.assertTrue(json.loads(outputs.pop().decode("utf-8"))["reformulation_results"])


class Instructions(unittest.TestCase):
    TEXTS = {
        "query SKILL.md": REPO / "query-llm-wiki" / "SKILL.md",
        "answer contract": REPO / "query-llm-wiki" / "references" / "answer-contract.md",
        "knowledge-skill template": REPO / "maintain-llm-wiki" / "assets" / "knowledge-skill" / "SKILL.template.md",
    }

    def test_reformulation_rules_are_in_all_three_instruction_texts(self) -> None:
        everywhere = ("--also", "--request -", "reformulation_results", "found_by", "\\uXXXX")
        rules = (
            "at most four reformulations", "200 characters",
            "Never let `reformulation_results` alone defeat an absence finding",
            "List every reformulation that was searched",
        )
        for label, path in self.TEXTS.items():
            text = path.read_text(encoding="utf-8")
            for phrase in everywhere + (rules if label != "query SKILL.md" else ()):
                with self.subTest(text=label, phrase=phrase):
                    self.assertIn(phrase, text)
        self.assertIn("lmwiki-search-coverage/3", self.TEXTS["answer contract"].read_text(encoding="utf-8"))
        self.assertIn("lmwiki-search-coverage/3", self.TEXTS["knowledge-skill template"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
