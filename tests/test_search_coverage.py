#!/usr/bin/env python3
"""The search's coverage block: losses are counted, never silent, and ranking is untouched.

The block adds keys only. These tests pin what each count means on a real
released harness wiki, including the identities a reader may rely on:
returned + omitted_count == matched, truncated exactly when something was
omitted, and omitted_top naming at most 20 of the omitted matches. Since format
2 the counts include the word forms each term lists under `forms`
(tests/test_wordforms.py pins the rules themselves).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "query-llm-wiki" / "scripts"))

import search_core  # noqa: E402
from harness import QUERY, TempWiki, Wiki, run, run_json  # noqa: E402
from test_lifecycle import SOURCE_MARKDOWN, add_cluster_and_concept  # noqa: E402

#: Enough matching pages that a limit of 1 omits more than OMITTED_TOP_LIMIT.
MANY = 24
NAVIGATION = {"WIKI.md", "meta/questions.md"}


def page(slug: str, title: str, description: str, claims: list[tuple[str, str]], source_id: str, source_stem: str) -> str:
    blocks = "\n\n".join(
        f"<!-- claim\nid: {claim_id}\nkind: fact\nstatus: active\nsources: {source_id}@page=1\n-->\n{text}\n<!-- /claim -->"
        for claim_id, text in claims
    )
    return f"""---
id: "concept-{slug}"
title: "{title}"
type: "concept"
status: "active"
created: "2026-09-06"
updated: "2026-09-06"
description: "{description}"
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

# {title}

{blocks}
"""


def build_coverage_wiki(wiki: Wiki) -> None:
    """Many pages sharing one word, a claim-heavy page, and a source-only word."""
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
    source_id, source_stem = record["source_id"], Path(record["path"]).stem
    add_cluster_and_concept(wiki)
    needed = MANY + 10 + 3
    claim_ids = iter(json.loads(wiki.locked("claim_id.py", "--count", str(needed)).stdout)["claim_ids"])

    pages: dict[str, str] = {}
    for number in range(1, MANY + 1):
        slug = f"messpunkt-{number:02d}"
        pages[f"wiki/concepts/{slug}.md"] = page(
            slug, f"Messpunkt {number}", f"Messpunkt Nummer {number} im Verteilnetz.",
            [(next(claim_ids), f"Der Messpunkt {number} wird jaehrlich durch den Netzbetreiber geprueft.")],
            source_id, source_stem,
        )
    pages["wiki/concepts/zaehlerstand.md"] = page(
        "zaehlerstand", "Zählerstand", "Ablesung und Meldung des Zählerstands.",
        [(next(claim_ids), f"Der Zählerstand wird in Fall {number} gesondert erfasst.") for number in range(1, 11)],
        source_id, source_stem,
    )
    pages["wiki/concepts/ablesung.md"] = page(
        "ablesung", "Ablesung", "Wie Werte erhoben werden.",
        [
            (next(claim_ids), "Die Ablesung erfolgt einmal im Jahr."),
            (next(claim_ids), "Der Kunde meldet den Wert selbst."),
            (next(claim_ids), "Abweichende Fristen gelten nur nach Vereinbarung."),
        ],
        source_id, source_stem,
    )

    staging = wiki.root / "staging"
    for relative, text in pages.items():
        staged = staging / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(text, encoding="utf-8")
    index = wiki.read("wiki/index.md").rstrip()
    for relative in pages:
        index += f"\n- [[{relative[:-3]}]]"
    wiki.write("wiki/index.md", index + "\n")
    plan_file = wiki.root / "batch.json"
    wiki.locked(
        "page_batch.py", "plan",
        "--staging-dir", str(staging),
        "--paths-json", json.dumps(sorted(pages)),
        "--output", str(plan_file),
    )
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    wiki.locked(
        "page_batch.py", "apply",
        "--staging-dir", str(staging),
        "--plan-file", str(plan_file),
        "--expect-plan-sha256", plan["plan_sha256"],
    )
    wiki.rebuild()
    wiki.release("coverage-1")


class CoverageOnAReleasedWiki(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._context = TempWiki()
        cls.wiki = cls._context.__enter__()
        build_coverage_wiki(cls.wiki)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._context.__exit__(None, None, None)

    def search(self, query: str, *extra: str, check: bool = True) -> dict:
        return self.wiki.query_json("search_wiki.py", "--target", str(self.wiki.path), "--query", query, *extra, check=check)

    def assert_identities(self, report: dict) -> None:
        coverage = report["coverage"]
        self.assertEqual(coverage["format"], "lmwiki-search-coverage/2")
        self.assertEqual(coverage["returned"], len(report["results"]))
        self.assertEqual(coverage["returned"] + coverage["omitted_count"], coverage["matched"])
        self.assertEqual(coverage["truncated"], coverage["omitted_count"] > 0)
        self.assertEqual(len(coverage["omitted_top"]), min(20, coverage["omitted_count"]))
        self.assertEqual(coverage["searched_files"], report["searched_files"])
        searched = [scope for scope, entry in coverage["scopes"].items() if entry["searched"]]
        self.assertEqual(sum(coverage["scopes"][scope]["files"] for scope in searched), coverage["searched_files"])
        if report["selector"] == {"kind": "all"}:
            # Every file holding a query term scores above zero, and only those do.
            self.assertEqual(
                sum(coverage["scopes"][scope]["files_with_a_query_term"] for scope in searched), coverage["matched"]
            )
        self.assertEqual(coverage["boundary"], search_core.COVERAGE_BOUNDARY)
        terms = [item["term"] for item in coverage["query_terms"]]
        for item in coverage["query_terms"]:
            self.assertLessEqual(len(item["forms"]), search_core.FORMS_LISTED)
            self.assertLessEqual(len(item["forms"]), item["forms_total"])
            self.assertTrue(all(0 < form["weight"] <= 1.0 for form in item["forms"]))
        self.assertTrue(set(coverage["form_only_terms"]).isdisjoint(coverage["unmatched_terms"]))
        for result in report["results"]:
            self.assertTrue(result["matched_terms"], result["path"])
            self.assertTrue(set(result["matched_terms"]) <= set(terms))
            # Every matched term is explained by at least one listed member.
            self.assertEqual(sorted({rule["term"] for rule in result["match_rules"]}), sorted(result["matched_terms"]))
            if result["navigation"]:
                self.assertTrue(all(rule["rule"] == "exact" for rule in result["match_rules"]))
            self.assertEqual(result["claims_returned"], len(result["claims"]))
            self.assertLessEqual(result["claims_returned"], result["claims_total"])
            self.assertEqual(
                result["navigation"],
                result["path"] in NAVIGATION or result["path"].rsplit("/", 1)[-1] == "index.md",
            )

    def test_truncation_is_counted_and_the_next_matches_are_named(self) -> None:
        narrow = self.search("Messpunkt", "--limit", "1")
        wide = self.search("Messpunkt", "--limit", "100")
        for report in (narrow, wide):
            self.assert_identities(report)
        self.assertGreater(narrow["coverage"]["matched"], 21)
        self.assertTrue(narrow["coverage"]["truncated"])
        self.assertEqual(narrow["coverage"]["omitted_count"], narrow["coverage"]["matched"] - 1)
        self.assertEqual(len(narrow["coverage"]["omitted_top"]), 20)
        self.assertEqual(
            narrow["coverage"]["omitted_top"],
            [{"path": item["path"], "score": item["score"]} for item in wide["results"][1:21]],
            "omitted_top names the very next matches, in rank order",
        )
        self.assertFalse(wide["coverage"]["truncated"])
        self.assertEqual(wide["coverage"]["omitted_count"], 0)
        self.assertEqual(wide["coverage"]["omitted_top"], [])
        self.assertEqual(wide["coverage"]["matched"], len(wide["results"]))

    def test_a_short_omission_names_every_omitted_match(self) -> None:
        wide = self.search("Messpunkt", "--limit", "100")
        limit = wide["coverage"]["matched"] - 3
        report = self.search("Messpunkt", "--limit", str(limit))
        self.assert_identities(report)
        self.assertEqual(report["coverage"]["omitted_count"], 3)
        self.assertEqual([item["path"] for item in report["coverage"]["omitted_top"]], [item["path"] for item in wide["results"][limit:]])

    def test_the_coverage_block_changes_no_ranking(self) -> None:
        """Results equal the first entries of a longer list: the limit only cuts."""
        short = self.search("Messpunkt Netzbetreiber")
        long = self.search("Messpunkt Netzbetreiber", "--limit", "100")
        self.assertEqual(short["results"], long["results"][: len(short["results"])])

    def test_withheld_claims_are_counted(self) -> None:
        report = self.search("Zählerstand")
        self.assert_identities(report)
        pages = {item["path"]: item for item in report["results"]}
        heavy = pages["wiki/concepts/zaehlerstand.md"]
        self.assertEqual(heavy["claims_total"], 10)
        self.assertEqual(heavy["claims_returned"], 8, "at most eight claims come back per page")
        partial = self.search("Ablesung")
        light = {item["path"]: item for item in partial["results"]}["wiki/concepts/ablesung.md"]
        self.assertEqual((light["claims_total"], light["claims_returned"]), (3, 1))

    def test_a_term_only_in_unsearched_sources_is_reported(self) -> None:
        report = self.search("Kilowattstunde")
        self.assert_identities(report)
        coverage = report["coverage"]
        self.assertEqual(report["results"], [])
        self.assertEqual(coverage["matched"], 0)
        self.assertEqual(coverage["unmatched_terms"], ["kilowattstunde"])
        self.assertEqual(coverage["terms_only_in_unsearched"], {"sources": ["kilowattstunde"]})
        self.assertEqual(coverage["scopes"]["sources"]["searched"], False)
        self.assertEqual(coverage["scopes"]["sources"]["files"], 1, "sources are counted even when not searched")
        self.assertEqual(coverage["scopes"]["sources"]["files_with_a_query_term"], 1)
        self.assertEqual(coverage["query_terms"], [
            {
                "term": "kilowattstunde", "origin": "query", "files": {"wiki": 0, "sources": 1, "history": None},
                "forms": [], "forms_total": 0,
            },
        ])
        self.assertEqual(coverage["form_only_terms"], [])

        with_sources = self.search("Kilowattstunde", "--include-sources")
        self.assert_identities(with_sources)
        self.assertEqual(with_sources["coverage"]["unmatched_terms"], [])
        self.assertEqual(with_sources["coverage"]["terms_only_in_unsearched"], {"sources": []})
        self.assertTrue(with_sources["coverage"]["scopes"]["sources"]["searched"])
        self.assertEqual([item["path"][:8] for item in with_sources["results"]], ["sources/"])

    def test_a_term_also_in_a_searched_file_is_not_reported_as_only_in_sources(self) -> None:
        """Only a term that no searched file holds sends the reader to --include-sources."""
        report = self.search("Netzbetreiber Kilowattstunde")
        self.assert_identities(report)
        coverage = report["coverage"]
        files = {item["term"]: item["files"] for item in coverage["query_terms"]}
        self.assertEqual(files["netzbetreiber"]["sources"], 1, "the unsearched source holds the word too")
        self.assertEqual(files["netzbetreiber"]["wiki"], MANY)
        self.assertEqual(coverage["terms_only_in_unsearched"], {"sources": ["kilowattstunde"]})
        self.assertEqual(coverage["unmatched_terms"], ["kilowattstunde"])

    def test_entries_that_are_not_regular_files_neither_count_nor_fail_the_search(self) -> None:
        """The release verifier skips them, so the search must not stumble over them either."""
        before = {flags: self.search("Netzbetreiber Kilowattstunde", *flags) for flags in ((), ("--include-sources",))}
        folders = [self.wiki.path / "sources" / "ordner.md", self.wiki.path / "wiki" / "concepts" / "ordner.md"]
        for folder in folders:
            folder.mkdir()
            self.addCleanup(folder.rmdir)
        dangling = self.wiki.path / "sources" / "verwaist.md"
        try:
            dangling.symlink_to(self.wiki.path / "fehlt" / "nirgends.md")
        except (OSError, NotImplementedError):
            pass  # Windows without symlink rights: the folders still cover the case.
        else:
            self.addCleanup(dangling.unlink)
        self.assertEqual(self.wiki.verify(query_side=True)["state"], "ready")
        for flags, expected in before.items():
            with self.subTest(flags=flags):
                report = self.search("Netzbetreiber Kilowattstunde", *flags)
                self.assertEqual(report["results"], expected["results"])
                self.assertEqual(report["coverage"], expected["coverage"])

    def test_concept_expansion_terms_are_labelled_and_matched_per_page(self) -> None:
        report = self.search("Netznutzungsentgelt")
        self.assert_identities(report)
        coverage = report["coverage"]
        origins = {item["term"]: item["origin"] for item in coverage["query_terms"]}
        self.assertEqual(origins["netznutzungsentgelt"], "query")
        self.assertEqual(origins["netzentgelt"], "concept-expansion")
        self.assertEqual(origins["arbeitspreis"], "concept-expansion")
        self.assertEqual(list(origins)[0], "netznutzungsentgelt", "the query's own words come first")
        # Only words of the query itself are reported as unmatched; an
        # expansion word that only the unsearched source holds is still named,
        # also when the source holds only a form of it ("Netzentgelte").
        self.assertEqual(coverage["unmatched_terms"], ["netznutzungsentgelt"])
        self.assertEqual(coverage["terms_only_in_unsearched"], {"sources": ["netzentgelt", "arbeitspreis"]})
        self.assertEqual(report["results"], [])
        with_sources = self.search("Netznutzungsentgelt", "--include-sources")
        self.assert_identities(with_sources)
        self.assertEqual(with_sources["coverage"]["unmatched_terms"], ["netznutzungsentgelt"])
        self.assertEqual(len(with_sources["results"]), 1)
        self.assertEqual(with_sources["results"][0]["matched_terms"], ["netzentgelt", "arbeitspreis"])
        self.assertIn(
            {"term": "netzentgelt", "token": "netzentgelte", "rule": "stem", "weight": 0.6},
            with_sources["results"][0]["match_rules"],
        )

    def test_dropped_words_are_reported_with_their_reason(self) -> None:
        report = self.search("die Messpunkt x und")
        self.assertEqual(report["coverage"]["dropped_terms"], [
            {"term": "die", "reason": "stopword"},
            {"term": "x", "reason": "single-character"},
            {"term": "und", "reason": "stopword"},
        ])
        self.assertEqual([item["term"] for item in report["coverage"]["query_terms"]], ["messpunkt"])
        # When nothing but stopwords is left, they are searched and not dropped.
        only = self.search("die")
        self.assertEqual(only["coverage"]["dropped_terms"], [])
        self.assertEqual(only["coverage"]["query_terms"][0]["term"], "die")

    def test_navigation_pages_are_flagged_and_stay_in_the_results(self) -> None:
        report = self.search("Messpunkt", "--limit", "100")
        self.assert_identities(report)
        flagged = [item["path"] for item in report["results"] if item["navigation"]]
        # The generated directory index lists every page title; link slugs such
        # as messpunkt-01 stay single tokens and match nothing.
        self.assertIn("wiki/concepts/index.md", flagged)
        self.assertNotIn("wiki/index.md", [item["path"] for item in report["results"]])
        content = [item["path"] for item in report["results"] if not item["navigation"]]
        self.assertEqual(len(content), MANY)
        self.assertTrue(all(path.startswith("wiki/concepts/messpunkt-") for path in content), content)

    def test_history_is_counted_only_when_searched(self) -> None:
        plain = self.search("Messpunkt")
        self.assertEqual(
            plain["coverage"]["scopes"]["history"],
            {"searched": False, "shipped": True, "files": None, "files_with_a_query_term": None},
        )
        self.assertIsNone(plain["coverage"]["query_terms"][0]["files"]["history"])
        with_history = self.search("Messpunkt", "--include-history")
        self.assert_identities(with_history)
        history = with_history["coverage"]["scopes"]["history"]
        self.assertTrue(history["searched"])
        self.assertIsInstance(history["files"], int)
        self.assertIsInstance(with_history["coverage"]["query_terms"][0]["files"]["history"], int)

    def test_a_selector_narrows_results_but_not_the_term_counts(self) -> None:
        selector = json.dumps({"kind": "filter", "conditions": [{"property": "__filename", "operator": "starts_with", "value": "messpunkt-0"}]})
        filtered = self.search("Messpunkt", "--filter-json", selector, "--limit", "100")
        unfiltered = self.search("Messpunkt", "--limit", "100")
        self.assert_identities(filtered)
        self.assertGreater(filtered["filtered_out"], 0)
        self.assertLess(filtered["coverage"]["matched"], unfiltered["coverage"]["matched"])
        self.assertEqual(filtered["coverage"]["scopes"], unfiltered["coverage"]["scopes"])
        self.assertEqual(filtered["coverage"]["query_terms"], unfiltered["coverage"]["query_terms"])

    def test_a_different_release_is_reported_as_snapshot_changed(self) -> None:
        current = self.wiki.verify(query_side=True)["manifest_sha256"]
        stale = "0" * 64
        result = self.wiki.query(
            "search_wiki.py", "--target", str(self.wiki.path), "--query", "Messpunkt",
            "--expect-manifest-sha256", stale, check=False,
        )
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["results"], [])
        self.assertEqual(report["release"]["state"], "snapshot_changed")
        self.assertEqual(report["release"]["expected_manifest_sha256"], stale)
        matching = self.search("Messpunkt", "--expect-manifest-sha256", current)
        self.assertEqual(matching["release"]["state"], "ready")
        self.assertTrue(matching["results"])

    def test_the_core_returns_what_the_command_line_prints(self) -> None:
        report = self.search("Messpunkt Zählerstand", "--include-sources", "--limit", "5")
        core = search_core.search(self.wiki.path, "Messpunkt Zählerstand", limit=5, include_sources=True)
        self.assertEqual(core["results"], report["results"])
        self.assertEqual(core["coverage"], report["coverage"])
        self.assertEqual(core["facets"], report["facets"])
        self.assertEqual(core["parser_errors"], [])


class CoreQueryTerms(unittest.TestCase):
    """The listed terms are exactly the tokens the ranking matches."""

    DEFINITIONS = {
        "netzentgelt": {"id": "netzentgelt", "status": "active", "terms": ["Netzentgelt", "Netznutzungsentgelt", "Arbeitspreis und Grundpreis"]},
        "kuendigung": {"id": "kuendigung", "status": "active", "terms": ["Kündigung", "Vertragsende"]},
    }

    def test_the_term_list_equals_the_ranked_token_set(self) -> None:
        for query, forms in (
            (query, forms)
            for query in (
                "Netznutzungsentgelt", "Kündigung für die Wohnung", "die und der", "a", "Arbeitspreis und Grundpreis",
                "Vertragsende Netzentgelt Netzentgelt", "x y Kündigung", "für", "Kündigungen und Netzentgelten",
            )
            for forms in (False, True)
        ):
            with self.subTest(query=query, forms=forms):
                ranked, _, expanded = search_core.expand_query(query, self.DEFINITIONS, forms)
                terms, dropped = search_core.query_terms(query, expanded, forms)
                names = [item["term"] for item in terms]
                self.assertEqual(set(names), ranked)
                self.assertEqual(len(names), len(set(names)))
                # A dropped word is one the ranking does not match, whatever brought it in.
                self.assertTrue(set(item["term"] for item in dropped).isdisjoint(ranked))

    def test_a_stopword_a_concept_term_brings_back_is_not_dropped(self) -> None:
        for query in ("Arbeitspreis und Grundpreis", "Netzentgelt und Umzug"):
            with self.subTest(query=query):
                _, _, expanded = search_core.expand_query(query, self.DEFINITIONS)
                terms, dropped = search_core.query_terms(query, expanded)
                self.assertEqual(dropped, [])
                self.assertIn({"term": "und", "origin": "concept-expansion"}, terms)
        _, _, expanded = search_core.expand_query("die Kündigung und x", self.DEFINITIONS)
        _, dropped = search_core.query_terms("die Kündigung und x", expanded)
        self.assertEqual(dropped, [
            {"term": "die", "reason": "stopword"},
            {"term": "und", "reason": "stopword"},
            {"term": "x", "reason": "single-character"},
        ])

    def test_an_empty_query_is_refused(self) -> None:
        with self.assertRaises(search_core.QueryError):
            search_core.search(Path("."), "  --  ", limit=1)


class ActionCatalogLists(unittest.TestCase):
    """The query catalog names every search flag argparse accepts, and only those."""

    def test_the_search_action_lists_the_helper_flags(self) -> None:
        catalog = run_json(QUERY / "describe_actions.py")
        actions = {item["id"]: item for item in catalog["actions"]}
        listed = {"--" + parameter["name"].replace("_", "-") for parameter in actions["search"]["parameters"]}
        helptext = run(QUERY / "search_wiki.py", "--help").stdout
        accepted = {word.rstrip(",") for word in helptext.split() if word.startswith("--")} - {"--help", "--target"}
        self.assertEqual(listed, accepted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
