#!/usr/bin/env python3
"""Search-quality gate on the synthetic fixture wiki (owner decision E4).

The fixed ranking tests elsewhere passed even under a prototype that pushed 14
required pages down, so they do not protect quality. This gate does. It builds
the fixture wiki in tests/fixtures/search_quality through the real helpers,
runs its 114 questions, and compares against expectations.json:

- no question whose first result was a required page loses that: a required
  page stays first, though two required pages may swap places;
- no required page that was in the top 3 leaves the top 3, and none that was in
  the top 12 (the default limit) leaves the top 12;
- a loss passes only when accepted_regressions lists the page with a reason;
  an entry with accepted_rank holds the page to that rank's bands from then on;
- the number of questions with a required first result, and of questions
  whose required pages are all found within 3, 12 and 100, does not fall below
  the recorded floors;
- the seven questions about topics the wiki does not hold return no more
  results within the default limit than recorded;
- navigation pages take no more top-3 slots than recorded.

expectations.json is regenerated only on purpose, with
tests/fixtures/search_quality/record_expectations.py, and the commit says why.

A second gate (ReformulationGate, Stufe 3) runs every question with each of two
blind sets of agent reformulations (reformulations.json) and compares against
reformulation_expectations.json: reformulations never change the question's own
results or coverage; the merged found counts (results plus
reformulation_results) stay at or above their floors; no required page leaves
the merged top 3 or top 12 it held; the block of the negative questions does not
grow; and no navigation page enters the block. It is recorded with
record_expectations.py --reformulations. The sets are a regression gate, never
a tuning target, and are never edited to make the gate pass.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "search_quality"
sys.path.insert(0, str(FIXTURE))

import quality  # noqa: E402

#: Where a build could leave bytecode: next to its data modules and next to the
#: helpers it runs, including helpers that other helpers start.
CACHE_FOLDERS = (
    FIXTURE / "content" / "__pycache__",
    quality.REPO / "maintain-llm-wiki" / "scripts" / "__pycache__",
    quality.QUERY_SCRIPTS / "__pycache__",
)


#: One fixture build for both gates of this module, made on first use.
_FIXTURE: dict = {}


def fixture() -> dict:
    if not _FIXTURE:
        directory = tempfile.mkdtemp(prefix="lmwiki-search-quality-")
        caches_before = {folder: folder.exists() for folder in CACHE_FOLDERS}
        wiki = quality.build(Path(directory) / "fixture")
        _FIXTURE.update(
            directory=directory,
            caches_before=caches_before,
            wiki=wiki,
            # Taken before this process imports the search core itself.
            caches_after_build={folder: folder.exists() for folder in CACHE_FOLDERS},
            core=quality.load_core(),
        )
    return _FIXTURE


def tearDownModule() -> None:
    if _FIXTURE:
        shutil.rmtree(_FIXTURE["directory"], ignore_errors=True)
        _FIXTURE.clear()


class SearchQualityGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        built = fixture()
        cls.caches_before = built["caches_before"]
        cls.wiki = built["wiki"]
        cls.caches_after_build = built["caches_after_build"]
        cls.ground_truth = quality.load_ground_truth()
        cls.expected = json.loads(quality.EXPECTATIONS.read_text(encoding="utf-8"))
        cls.core = built["core"]
        cls.measured = quality.measure(cls.wiki, cls.ground_truth, cls.core)

    def test_the_expectations_describe_the_ground_truth(self) -> None:
        self.assertEqual(self.expected["format"], quality.EXPECTATIONS_FORMAT)
        self.assertEqual(sorted(self.expected["queries"]), sorted(item["id"] for item in self.ground_truth))
        for item in self.ground_truth:
            with self.subTest(query=item["id"]):
                entry = self.expected["queries"][item["id"]]
                self.assertEqual(sorted(entry["must_find_ranks"]), sorted(item["must_find"]))
                self.assertEqual("with_required_flags" in entry, bool(item.get("requires_flags")))

    def test_no_question_loses_rank_1_and_no_required_page_the_top_3_or_12(self) -> None:
        problems = quality.rank_regressions(self.expected, self.measured)
        self.assertEqual(
            problems,
            [],
            "required pages lost their place; fix the ranking, or list them in accepted_regressions "
            "with a reason, or re-record expectations deliberately:\n" + "\n".join(problems),
        )

    def test_found_counts_stay_at_or_above_the_floors(self) -> None:
        totals = self.measured["aggregates"]
        for key, floor in self.expected["floors"].items():
            with self.subTest(measure=key):
                self.assertGreaterEqual(totals[key], floor)

    def test_questions_about_absent_topics_stay_capped(self) -> None:
        cap = self.expected["caps"]["negative_results_within_12"]
        self.assertLessEqual(self.measured["aggregates"]["negative_results_within_12"], cap)

    def test_navigation_pages_win_no_more_top_3_slots(self) -> None:
        cap = self.expected["caps"]["navigation_in_top_3"]
        self.assertLessEqual(self.measured["aggregates"]["navigation_in_top_3"], cap)

    def test_accepted_regressions_name_a_required_page_and_a_reason(self) -> None:
        must_find = {item["id"]: set(item["must_find"]) for item in self.ground_truth}
        for entry in self.expected["accepted_regressions"]:
            with self.subTest(entry=entry):
                self.assertIn(entry.get("path"), must_find.get(entry.get("id"), set()))
                self.assertTrue(str(entry.get("reason") or "").strip(), "an accepted regression needs a reason")
                if "accepted_rank" in entry:
                    held = entry["accepted_rank"]
                    self.assertTrue(held is None or (isinstance(held, int) and 1 <= held <= quality.RANK_LIMIT))

    def test_the_build_wrote_nothing_into_the_repository(self) -> None:
        for name in ("wiki", "work", "source_map.json", "fixture_report.json", "claim_index.json"):
            with self.subTest(name=name):
                self.assertFalse((FIXTURE / name).exists())
        # Only a folder that did not exist before can show what the build left.
        for folder, existed in self.caches_before.items():
            if not existed:
                with self.subTest(folder=folder.relative_to(quality.REPO).as_posix()):
                    self.assertFalse(self.caches_after_build[folder], "the build cached bytecode in the repository")

    def test_the_command_line_ranks_like_the_core(self) -> None:
        """A few real CLI calls, so the gate also covers the wrapper."""
        script = quality.QUERY_SCRIPTS / "search_wiki.py"
        by_id = {item["id"]: item for item in self.ground_truth}
        cases = (("ex-01", []), ("ne-01", []), ("so-01", ["--include-sources"]), ("ex-04", ["--limit", "100"]))
        for query_id, extra in cases:
            with self.subTest(query=query_id, flags=extra):
                result = subprocess.run(
                    [sys.executable, "-B", str(script), "--target", str(self.wiki), "--query", by_id[query_id]["query"], *extra],
                    capture_output=True,
                    encoding="utf-8",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                limit = int(extra[1]) if extra[:1] == ["--limit"] else 12
                core = self.core.search(
                    self.wiki, by_id[query_id]["query"], limit=limit, include_sources="--include-sources" in extra
                )
                self.assertEqual(
                    [(item["path"], item["score"]) for item in report["results"]],
                    [(item["path"], item["score"]) for item in core["results"]],
                )
                self.assertEqual(report["coverage"], core["coverage"])
                self.assertEqual(report["release"]["state"], "ready")


class ReformulationGate(unittest.TestCase):
    """The second gate: the agent's reformulations, from two blind sets."""

    @classmethod
    def setUpClass(cls) -> None:
        built = fixture()
        cls.wiki = built["wiki"]
        cls.core = built["core"]
        cls.ground_truth = quality.load_ground_truth()
        cls.sets = quality.load_reformulations()
        cls.expected = json.loads(quality.REFORMULATION_EXPECTATIONS.read_text(encoding="utf-8"))
        cls.measured = quality.measure_reformulations(cls.wiki, cls.ground_truth, cls.sets, cls.core)

    def aggregates(self, name: str) -> dict:
        return self.measured["sets"][name]["aggregates"]

    def test_the_sets_are_valid_requests(self) -> None:
        ids = sorted(item["id"] for item in self.ground_truth)
        self.assertEqual(sorted(self.sets), ["A", "B"])
        for name, questions in self.sets.items():
            with self.subTest(set=name):
                self.assertEqual(sorted(questions), ids)
                for query_id, also in questions.items():
                    self.assertIsInstance(also, list, query_id)
                    self.assertLessEqual(len(also), self.core.MAX_ALSO, query_id)
                    self.assertTrue(all(isinstance(entry, str) for entry in also), query_id)
                    self.core.check_also(also)

    def test_the_expectations_describe_the_sets_and_the_ground_truth(self) -> None:
        self.assertEqual(self.expected["format"], quality.REFORMULATION_FORMAT)
        self.assertEqual(sorted(self.expected["sets"]), sorted(self.sets))
        for name, recorded in self.expected["sets"].items():
            with self.subTest(set=name):
                self.assertEqual(sorted(recorded["queries"]), sorted(item["id"] for item in self.ground_truth))
                self.assertEqual(recorded["caps"]["navigation_in_block"], 0)
                for item in self.ground_truth:
                    entry = recorded["queries"][item["id"]]
                    self.assertEqual(sorted(entry["merged_ranks"]), sorted(item["must_find"]))
                    self.assertEqual("with_required_flags" in entry, bool(item.get("requires_flags")))
        for entry in self.expected["accepted_regressions"]:
            with self.subTest(entry=entry):
                must_find = {item["id"]: set(item["must_find"]) for item in self.ground_truth}
                self.assertIn(entry.get("set"), self.sets)
                self.assertIn(entry.get("path"), must_find.get(entry.get("id"), set()))
                self.assertTrue(str(entry.get("reason") or "").strip(), "an accepted regression needs a reason")

    def test_reformulations_never_change_the_question_results(self) -> None:
        for name in sorted(self.sets):
            with self.subTest(set=name):
                changed = [
                    query_id for query_id, entry in self.measured["sets"][name]["queries"].items() if not entry["identical"]
                ]
                self.assertEqual(changed, [], "the question's results or coverage changed with reformulations")
                totals = self.aggregates(name)
                self.assertEqual(totals["identity_failures"], 0)

    def test_merged_found_counts_stay_at_or_above_the_floors(self) -> None:
        for name, recorded in self.expected["sets"].items():
            for key, floor in recorded["floors"].items():
                with self.subTest(set=name, measure=key):
                    self.assertGreaterEqual(self.aggregates(name)[key], floor)

    def test_no_required_page_leaves_the_merged_top_3_or_12(self) -> None:
        problems = quality.reformulation_regressions(self.expected, self.measured)
        self.assertEqual(
            problems,
            [],
            "required pages left the merged top 3 or 12; fix the cause, list them in accepted_regressions with a "
            "reason, or re-record deliberately:\n" + "\n".join(problems),
        )

    def test_negative_questions_block_entries_stay_capped(self) -> None:
        for name, recorded in self.expected["sets"].items():
            with self.subTest(set=name):
                cap = recorded["caps"]["negative_block_within_12"]
                self.assertLessEqual(self.aggregates(name)["negative_block_within_12"], cap)

    def test_no_navigation_page_enters_the_block(self) -> None:
        for name in sorted(self.sets):
            with self.subTest(set=name):
                self.assertEqual(self.aggregates(name)["navigation_in_block"], 0)

    def test_the_command_line_fuses_like_the_core(self) -> None:
        """One real CLI call with reformulations, so the gate also covers the wrapper."""
        script = quality.QUERY_SCRIPTS / "search_wiki.py"
        item = {entry["id"]: entry for entry in self.ground_truth}["pa-01"]
        also = self.sets["A"]["pa-01"]
        result = subprocess.run(
            [sys.executable, "-B", str(script), "--target", str(self.wiki), "--query", item["query"],
             *[f"--also={entry}" for entry in also]],
            capture_output=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        core = self.core.search(self.wiki, item["query"], also=also, limit=12)
        for key in ("formulations", "dropped_formulations", "results", "reformulation_results", "coverage"):
            self.assertEqual(report[key], core[key], key)
        self.assertTrue(report["reformulation_results"])


class MergedRankRule(unittest.TestCase):
    """The merged rank is the better of the result rank and the block position."""

    @staticmethod
    def measured(ranks: dict) -> dict:
        return {"sets": {"A": {"queries": {"q": {"merged_ranks": ranks}}}}}

    def test_a_page_may_move_from_results_to_the_block_inside_its_band(self) -> None:
        expected = {"sets": {"A": {"queries": {"q": {"merged_ranks": {"a.md": {"results": 2, "block": None}}}}}},
                    "accepted_regressions": []}
        self.assertEqual(quality.reformulation_regressions(expected, self.measured({"a.md": {"results": 40, "block": 3}})), [])
        problems = quality.reformulation_regressions(expected, self.measured({"a.md": {"results": 40, "block": 5}}))
        self.assertEqual(problems, ["set A, q (without flags): a.md left the merged top 3: merged rank 2 -> merged rank 5"])

    def test_an_accepted_page_is_held_to_its_accepted_rank(self) -> None:
        expected = {
            "sets": {"A": {"queries": {"q": {"merged_ranks": {"a.md": {"results": 2, "block": None}}}}}},
            "accepted_regressions": [{"set": "A", "id": "q", "path": "a.md", "reason": "test", "accepted_rank": 9}],
        }
        self.assertEqual(quality.reformulation_regressions(expected, self.measured({"a.md": {"results": None, "block": 9}})), [])
        self.assertEqual(
            quality.reformulation_regressions(expected, self.measured({"a.md": {"results": None, "block": None}})),
            ["set A, q (without flags): a.md left the merged top 12: merged rank 9 -> not in the merged top 12"],
        )


class RankOneRule(unittest.TestCase):
    """Rank 1 is judged per question, without building the fixture."""

    @staticmethod
    def check(recorded: dict, now: dict, accepted: tuple = ()) -> list[str]:
        expected = {
            "queries": {"q": {"must_find_ranks": recorded}},
            "accepted_regressions": [{"id": "q", "path": path, "reason": "test"} for path in accepted],
        }
        return quality.rank_regressions(expected, {"queries": {"q": {"must_find_ranks": now}}})

    def test_losing_rank_1_inside_the_top_3_is_a_regression(self) -> None:
        problems = self.check({"a.md": 1}, {"a.md": 2})
        self.assertEqual(problems, ["q (without flags): a.md lost rank 1 and no required page took it: rank 1 -> rank 2"])

    def test_two_required_pages_may_swap_places(self) -> None:
        self.assertEqual(self.check({"a.md": 1, "b.md": 2}, {"a.md": 2, "b.md": 1}), [])

    def test_an_accepted_page_may_lose_rank_1(self) -> None:
        self.assertEqual(self.check({"a.md": 1}, {"a.md": 3}, accepted=("a.md",)), [])

    def test_an_accepted_rank_holds_the_page_to_its_new_bands(self) -> None:
        expected = {
            "queries": {"q": {"must_find_ranks": {"a.md": 3}}},
            "accepted_regressions": [{"id": "q", "path": "a.md", "reason": "test", "accepted_rank": 4}],
        }
        now = lambda rank: {"queries": {"q": {"must_find_ranks": {"a.md": rank}}}}  # noqa: E731
        self.assertEqual(quality.rank_regressions(expected, now(4)), [])
        self.assertEqual(quality.rank_regressions(expected, now(9)), [])
        self.assertEqual(
            quality.rank_regressions(expected, now(13)), ["q (without flags): a.md left the top 12: rank 4 -> rank 13"]
        )

    def test_a_page_that_leaves_the_top_3_is_reported_for_both(self) -> None:
        problems = self.check({"a.md": 1}, {"a.md": 5})
        self.assertEqual(len(problems), 2)
        self.assertIn("lost rank 1", problems[0])
        self.assertIn("left the top 3", problems[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
