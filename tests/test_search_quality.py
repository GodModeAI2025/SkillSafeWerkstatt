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
- the number of questions with a required first result, and of questions
  whose required pages are all found within 3, 12 and 100, does not fall below
  the recorded floors;
- the seven questions about topics the wiki does not hold return no more
  results within the default limit than recorded;
- navigation pages take no more top-3 slots than recorded.

expectations.json is regenerated only on purpose, with
tests/fixtures/search_quality/record_expectations.py, and the commit says why.
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


class SearchQualityGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.mkdtemp(prefix="lmwiki-search-quality-")
        cls.caches_before = {folder: folder.exists() for folder in CACHE_FOLDERS}
        cls.wiki = quality.build(Path(cls._dir) / "fixture")
        # Taken before this process imports the search core itself.
        cls.caches_after_build = {folder: folder.exists() for folder in CACHE_FOLDERS}
        cls.ground_truth = quality.load_ground_truth()
        cls.expected = json.loads(quality.EXPECTATIONS.read_text(encoding="utf-8"))
        cls.core = quality.load_core()
        cls.measured = quality.measure(cls.wiki, cls.ground_truth, cls.core)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._dir, ignore_errors=True)

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

    def test_a_page_that_leaves_the_top_3_is_reported_for_both(self) -> None:
        problems = self.check({"a.md": 1}, {"a.md": 5})
        self.assertEqual(len(problems), 2)
        self.assertIn("lost rank 1", problems[0])
        self.assertIn("left the top 3", problems[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
