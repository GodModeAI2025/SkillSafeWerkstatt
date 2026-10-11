#!/usr/bin/env python3
"""Consent-gated decision layer: config gate, provider contract, and read-only behaviour.

The decision layer is optional by design. These tests pin that contract: a
wiki without a configured layer keeps the standard deterministic behavior, a
configured layer only calls its provider after recorded consent, every
transport or response problem degrades to the deterministic fallback, and the
query side never changes the wiki. The provider itself is tested against a
local canned HTTP server, so the suite stays offline and deterministic.
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import decision_provider  # noqa: E402
from harness import TempWiki, Wiki  # noqa: E402
from test_integration import build_large_wiki  # noqa: E402

API_KEY_ENV = "TEST_DECISION_LAYER_KEY"
API_KEY_VALUE = "test-provider-key"


class CannedProvider(http.server.BaseHTTPRequestHandler):
    """Answers every POST from a class-level responder; records the last request."""

    responder: Callable[[bytes], str] = lambda body: json.dumps({"answers": []})
    last_authorization: str = ""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        CannedProvider.last_authorization = str(self.headers.get("Authorization", ""))
        payload = CannedProvider.responder(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        pass


def start_provider(responder: Callable[[bytes], str]) -> tuple[http.server.HTTPServer, str, threading.Thread]:
    server = http.server.HTTPServer(("127.0.0.1", 0), CannedProvider)
    CannedProvider.responder = responder
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", thread


def answers_for(body: bytes, builder: Callable[[dict[str, Any]], dict[str, Any]]) -> str:
    request = json.loads(body)
    return json.dumps({"answers": [builder(question) for question in request["questions"]]})


def config_text(endpoint: str, *, enabled: bool = True, consent_by: str = "human:test",
                consent_at: str = "2026-10-10T10:00:00Z", max_links: int = 5,
                max_notes_per_cluster: int = 40) -> str:
    return f"""---
schema_version: 1
status: "active"
enabled: {str(enabled).lower()}
provider: "http"
endpoint: "{endpoint}"
model: "test-model-1"
api_key_env: "{API_KEY_ENV}"
consent_by: "{consent_by}"
consent_at: "{consent_at}"
timeout_seconds: 10
attempts: 1
state_chars: 6000
request_chars: 90000
tau_route: 0.6
tau_path: 0.5
tau_ing: 0.5
tau_cons: 0.6
tau_link: 0.6
tau_fold: 0.08
tau_ret: 0.1
beam: 2
k: 8
max_depth: 4
max_links: {max_links}
max_notes_per_cluster: {max_notes_per_cluster}
updated: "2026-10-10"
---

# Optionale Entscheidungsschicht

Testkonfiguration.
"""


def enable_layer(wiki: Wiki, endpoint: str, **kwargs: Any) -> None:
    import uuid

    wiki.write("schema/DECISION_LAYER.md", config_text(endpoint, **kwargs))
    wiki.release("decision-layer-config-" + uuid.uuid4().hex[:8])


def candidate_note(path: Path, title: str = "Neuer Verteilnetzbegriff") -> Path:
    path.write_text(
        f"""---
id: "concept-{path.stem}"
title: "{title}"
type: "concept"
status: "draft"
created: "2026-10-10"
updated: "2026-10-10"
description: "Beschreibung des Kandidaten: {title}."
language: "de"
sources: []
clusters: []
concepts: []
tags:
  - "type/wiki-concept"
---

# {title}

Inhalt des Kandidaten.
""",
        encoding="utf-8",
    )
    return path


class Fixture:
    """A released wiki with one concept cluster directory to route into."""

    @staticmethod
    def build(wiki: Wiki) -> None:
        build_large_wiki(wiki)
        clusters = wiki.read("schema/CLUSTERS.md")
        wiki.write(
            "schema/CLUSTERS.md",
            clusters.rstrip()
            + (
                "\n\n## netzbetrieb\n"
                "- Label: Netzbetrieb\n"
                "- Color: #FE8F11\n"
                "- Status: active\n"
                "- Purpose: Betrieb und Steuerung des Verteilnetzes\n"
                "- Directory: wiki/concepts/netzbetrieb\n"
            ),
        )
        staging = wiki.root / "staging-netzbetrieb"
        relative = "wiki/concepts/netzbetrieb/netzbetrieb-grundlagen.md"
        staged = staging / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(
            """---
id: "concept-netzbetrieb-grundlagen"
title: "Netzbetrieb Grundlagen"
type: "concept"
status: "draft"
created: "2026-10-10"
updated: "2026-10-10"
description: "Grundlagen des Netzbetriebs."
language: "de"
sources: []
clusters:
  - "netzbetrieb"
concepts: []
tags:
  - "type/wiki-concept"
---

# Netzbetrieb Grundlagen

Grundlagen des Netzbetriebs.
""",
            encoding="utf-8",
        )
        index = wiki.read("wiki/index.md").rstrip() + "\n- [[wiki/concepts/netzbetrieb/netzbetrieb-grundlagen|Netzbetrieb Grundlagen]]\n"
        wiki.write("wiki/index.md", index)
        plan_file = wiki.root / "netzbetrieb-batch.json"
        wiki.locked(
            "page_batch.py", "plan",
            "--staging-dir", str(staging),
            "--paths-json", json.dumps([relative]),
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


class ProviderUnit(unittest.TestCase):
    """The vendor-neutral decision contract, independent of any wiki."""

    def test_confidence_measures_concentration_not_correctness(self) -> None:
        self.assertEqual(decision_provider.confidence_yes_no(0.2), 0.8)
        self.assertEqual(decision_provider.confidence_yes_no(0.9), 0.9)
        self.assertAlmostEqual(decision_provider.confidence_choice({"a": 0.9, "b": 0.1}), 0.9)

    def test_path_score_is_the_geometric_mean_of_edge_probabilities(self) -> None:
        self.assertAlmostEqual(decision_provider.geometric_mean([0.5, 0.25]), (0.5 * 0.25) ** 0.5)
        self.assertEqual(decision_provider.geometric_mean([0.0, 1.0]), 0.0)
        self.assertEqual(decision_provider.geometric_mean([]), 0.0)

    def test_request_budget_is_enforced(self) -> None:
        config = {"state_chars": 1000, "request_chars": 100, "model": "m"}
        with self.assertRaises(decision_provider.DecisionError):
            decision_provider.build_request(config, "x" * 200, [decision_provider.question_yes_no("q", "Frage")])
        with self.assertRaises(decision_provider.DecisionError):
            decision_provider.build_request(config, " ", [decision_provider.question_yes_no("q", "Frage")])

    def test_option_limit_matches_the_vendor_bound(self) -> None:
        with self.assertRaises(decision_provider.DecisionError):
            decision_provider.question_choice("q", "Frage?", [f"o{i}" for i in range(decision_provider.MAX_OPTIONS + 1)])

    def test_response_contract_is_strict(self) -> None:
        request = {
            "questions": [
                {"id": "a", "type": "choice", "question": "?", "options": ["x", "y"]},
                {"id": "b", "type": "yes_no", "question": "?"},
            ]
        }
        good = {"answers": [{"id": "a", "type": "choice", "probabilities": {"x": 0.7, "y": 0.3}},
                            {"id": "b", "type": "yes_no", "probability": 0.4}]}
        normalized = decision_provider.validate_response(request, good)
        self.assertEqual(set(normalized), {"a", "b"})
        missing = {"answers": [{"id": "a", "type": "choice", "probabilities": {"x": 0.7, "y": 0.3}}]}
        with self.assertRaises(decision_provider.DecisionError):
            decision_provider.validate_response(request, missing)
        with self.assertRaises(decision_provider.DecisionError):
            decision_provider.validate_response(request, {"answers": []})
        wrong_options = {"answers": [{"id": "a", "type": "choice", "probabilities": {"x": 0.5, "z": 0.5}},
                                     {"id": "b", "type": "yes_no", "probability": 0.4}]}
        with self.assertRaises(decision_provider.DecisionError):
            decision_provider.validate_response(request, wrong_options)
        bad_sum = {"answers": [{"id": "a", "type": "choice", "probabilities": {"x": 0.9, "y": 0.9}},
                               {"id": "b", "type": "yes_no", "probability": 0.4}]}
        with self.assertRaises(decision_provider.DecisionError):
            decision_provider.validate_response(request, bad_sum)

    def test_a_fresh_wiki_is_inactive(self) -> None:
        with TempWiki() as wiki:
            loaded = decision_provider.load_config(wiki.path)
            self.assertEqual(loaded["state"], "inactive")
            self.assertTrue(loaded["config"].get("exists"))

    def test_clamp_state_compacts_and_truncates(self) -> None:
        self.assertEqual(decision_provider.clamp_state("a  b\nc", 100), "a b c")
        self.assertEqual(len(decision_provider.clamp_state("x" * 500, 100)), 100)


class ConfigGate(unittest.TestCase):
    """The layer stays off until file, enablement, and consent all agree."""

    def test_disabled_layer_falls_back_to_bounded_bm25(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            wiki.release("fixture-1")
            os.environ.pop(API_KEY_ENV, None)
            report = wiki.query_json(
                "score_notes.py", "--target", str(wiki.path), "--query", "Netzentgelte"
            )
            self.assertEqual(report["state"], "inactive")
            self.assertEqual(report["fallback"], "bm25")
            self.assertTrue(report["notes"])

    def test_enabled_without_consent_is_refused_and_warned(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            server, endpoint, _ = start_provider(lambda body: "{}")
            try:
                enable_layer(wiki, endpoint, consent_by="", consent_at="")
                report = wiki.query_json(
                    "score_notes.py", "--target", str(wiki.path), "--query", "Netzentgelte"
                )
                self.assertEqual(report["state"], "consent_required")
                self.assertEqual(report["fallback"], "bm25")
                lint = json.loads(wiki.lint().stdout)
                self.assertTrue(
                    any("consent" in message for message in lint["warnings"]),
                    lint["warnings"],
                )
            finally:
                server.shutdown()

    def test_enabled_with_empty_endpoint_is_a_lint_error(self) -> None:
        # A misconfigured layer cannot be released (the linter blocks it), so the
        # query side can only ever observe released, consistent states. The
        # misconfigured state itself is pinned at the linter boundary.
        with TempWiki() as wiki:
            Fixture.build(wiki)
            wiki.write("schema/DECISION_LAYER.md", config_text(""))
            lint = json.loads(wiki.lint().stdout)
            self.assertFalse(lint["valid"])
            self.assertTrue(any("DECISION_LAYER" in message for message in lint["errors"]), lint["errors"])

    def test_malformed_frontmatter_is_a_lint_error(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            wiki.write("schema/DECISION_LAYER.md", "---\nstatus: [nested: not allowed]\n---\n\n# X\n")
            lint = json.loads(wiki.lint().stdout)
            self.assertFalse(lint["valid"])
            self.assertTrue(any("DECISION_LAYER" in message for message in lint["errors"]))


class QueryScoring(unittest.TestCase):
    """score_notes re-ranks BM25 candidates through the provider and degrades honestly."""

    def run_score(self, wiki: Wiki, responder: Callable[[bytes], str]) -> dict[str, Any]:
        return wiki.query_json("score_notes.py", "--target", str(wiki.path), "--query", "Netzentgelte")

    def test_scored_notes_are_ranked_by_probability_above_the_threshold(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                def responder(body: bytes) -> str:
                    return answers_for(body, lambda question: {
                        "id": question["id"],
                        "type": "yes_no",
                        "probability": {1: 0.2, 2: 0.9, 3: 0.05}.get(
                            int(question["id"].split("-")[1]), 0.1
                        ),
                    })

                server, endpoint, _ = start_provider(responder)
                try:
                    enable_layer(wiki, endpoint)
                    report = self.run_score(wiki, responder)
                    self.assertEqual(report["state"], "scored")
                    self.assertEqual(report["fallback"], "none")
                    probabilities = [note["probability"] for note in report["notes"]]
                    self.assertEqual(probabilities, sorted(probabilities, reverse=True))
                    self.assertTrue(all(probability > 0.1 for probability in probabilities))
                    self.assertEqual(report["notes"][0]["probability"], 0.9)
                    self.assertEqual(CannedProvider.last_authorization, f"Bearer {API_KEY_VALUE}")
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_no_note_above_threshold_falls_back_to_bm25(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                server, endpoint, _ = start_provider(
                    lambda body: answers_for(body, lambda question: {"id": question["id"], "type": "yes_no", "probability": 0.05})
                )
                try:
                    enable_layer(wiki, endpoint)
                    report = self.run_score(wiki, lambda body: "")
                    self.assertEqual(report["state"], "no_candidates_above_threshold")
                    self.assertEqual(report["fallback"], "bm25")
                    self.assertTrue(report["notes"])
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_missing_api_key_never_calls_the_provider(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ.pop(API_KEY_ENV, None)
            server, endpoint, _ = start_provider(lambda body: "{}")
            try:
                enable_layer(wiki, endpoint)
                report = self.run_score(wiki, lambda body: "")
                self.assertEqual(report["state"], "provider_unavailable")
                self.assertIn(API_KEY_ENV, report["reason"])
                self.assertEqual(report["fallback"], "bm25")
                self.assertTrue(report["notes"])
            finally:
                server.shutdown()
                os.environ.pop(API_KEY_ENV, None)

    def test_unreachable_provider_degrades_to_bm25(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                enable_layer(wiki, "http://127.0.0.1:1")
                report = self.run_score(wiki, lambda body: "")
                self.assertEqual(report["state"], "provider_unavailable")
                self.assertEqual(report["fallback"], "bm25")
                self.assertTrue(report["notes"])
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_invalid_response_degrades_to_bm25(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                server, endpoint, _ = start_provider(lambda body: "not json at all")
                try:
                    enable_layer(wiki, endpoint)
                    report = self.run_score(wiki, lambda body: "")
                    self.assertEqual(report["state"], "provider_unavailable")
                finally:
                    server.shutdown()
                server, endpoint, _ = start_provider(
                    lambda body: answers_for(body, lambda question: {"id": "unknown", "type": "yes_no", "probability": 0.5})
                )
                try:
                    enable_layer(wiki, endpoint)
                    report = self.run_score(wiki, lambda body: "")
                    self.assertEqual(report["state"], "provider_invalid_response")
                    self.assertEqual(report["fallback"], "bm25")
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_query_side_never_changes_the_wiki(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                server, endpoint, _ = start_provider(
                    lambda body: answers_for(body, lambda question: {"id": question["id"], "type": "yes_no", "probability": 0.9})
                )
                try:
                    enable_layer(wiki, endpoint)
                    before = wiki.verify(query_side=True)
                    for _ in range(3):
                        report = self.run_score(wiki, lambda body: "")
                        self.assertEqual(report["state"], "scored")
                    after = wiki.verify(query_side=True)
                    self.assertEqual(after["state"], "ready")
                    self.assertEqual(before["manifest_sha256"], after["manifest_sha256"])
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)


class MaintainDecisions(unittest.TestCase):
    """Routing, consolidation, linking, and clustering stay proposals until confirmed."""

    def route(self, wiki: Wiki) -> dict[str, Any]:
        note = candidate_note(wiki.root / "candidate.md")
        return json.loads(
            wiki.locked(
                "route_source.py",
                "--note-file", str(note),
            ).stdout
        )

    def test_route_chooses_the_provider_folder(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                def responder(body: bytes) -> str:
                    return answers_for(body, lambda question: {
                        "id": question["id"],
                        "type": "choice",
                        "probabilities": {"wiki/concepts/netzbetrieb": 0.9, "here": 0.05, "new": 0.05},
                    })

                server, endpoint, _ = start_provider(responder)
                try:
                    enable_layer(wiki, endpoint)
                    report = self.route(wiki)
                    self.assertEqual(report["state"], "routed")
                    self.assertEqual(report["folder"], "wiki/concepts/netzbetrieb")
                    self.assertEqual(report["probability"], 0.9)
                    self.assertTrue(any(
                        note["path"] == "wiki/concepts/netzbetrieb/netzbetrieb-grundlagen.md"
                        for note in report["candidate_notes"]
                    ), report["candidate_notes"])
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_route_new_never_creates_a_folder(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                server, endpoint, _ = start_provider(
                    lambda body: answers_for(body, lambda question: {
                        "id": question["id"],
                        "type": "choice",
                        "probabilities": {"new": 0.9, "here": 0.05, "wiki/concepts/netzbetrieb": 0.05},
                    })
                )
                try:
                    enable_layer(wiki, endpoint)
                    report = self.route(wiki)
                    self.assertEqual(report["state"], "new_cluster_requested")
                    self.assertFalse((wiki.path / "wiki/concepts/netzbetrieb/neu").exists())
                    self.assertIn("CLUSTERS.md", report["reason"])
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_route_low_confidence_returns_the_beam(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                server, endpoint, _ = start_provider(
                    lambda body: answers_for(body, lambda question: {
                        "id": question["id"],
                        "type": "choice",
                        "probabilities": {"wiki/concepts/netzbetrieb": 0.4, "here": 0.35, "new": 0.25},
                    })
                )
                try:
                    enable_layer(wiki, endpoint)
                    report = self.route(wiki)
                    self.assertEqual(report["state"], "low_confidence")
                    self.assertEqual(report["fallback"], "agent_decision")
                    self.assertEqual(len(report["beam"]), 2)
                    self.assertEqual(report["beam"][0]["option"], "wiki/concepts/netzbetrieb")
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_route_inactive_layer_reports_the_options_for_manual_decision(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            wiki.release("fixture-2")
            os.environ.pop(API_KEY_ENV, None)
            report = self.route(wiki)
            self.assertEqual(report["state"], "inactive")
            self.assertIn("wiki/concepts/netzbetrieb", report["options"])
            self.assertIn("here", report["options"])
            self.assertIn("new", report["options"])
            self.assertNotIn("none_of_these", report["options"])

    def test_consolidation_below_threshold_creates_a_new_note(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                note = candidate_note(wiki.root / "candidate.md", "Verwandter Verteilnetzbegriff")
                server, endpoint, _ = start_provider(
                    lambda body: answers_for(body, lambda question: {
                        "id": question["id"],
                        "type": "choice",
                        "probabilities": {"modify": 0.5, "new_note": 0.5},
                    })
                )
                try:
                    enable_layer(wiki, endpoint)
                    report = json.loads(
                        wiki.locked(
                            "plan_consolidation.py",
                            "--note-file", str(note),
                            "--page", "wiki/concepts/netzentgelte.md",
                        ).stdout
                    )
                    self.assertEqual(report["state"], "decided")
                    self.assertEqual(report["decision"], "new_note")
                    self.assertIn("tau_cons", report["rule"])
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_consolidation_confident_modify_takes_the_modify_path(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                note = candidate_note(wiki.root / "candidate.md", "Netzentgelte Erlaeterung")
                server, endpoint, _ = start_provider(
                    lambda body: answers_for(body, lambda question: {
                        "id": question["id"],
                        "type": "choice",
                        "probabilities": {"modify": 0.9, "new_note": 0.1},
                    })
                )
                try:
                    enable_layer(wiki, endpoint)
                    report = json.loads(
                        wiki.locked(
                            "plan_consolidation.py",
                            "--note-file", str(note),
                            "--page", "wiki/concepts/netzentgelte.md",
                        ).stdout
                    )
                    self.assertEqual(report["decision"], "modify")
                    self.assertIn("page-batch", report["instruction"])
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_related_links_are_capped_and_bidirectional(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                def responder(body: bytes) -> str:
                    request = json.loads(body)
                    by_index = {q["id"]: q for q in request["questions"]}
                    values = {1: 0.9, 2: 0.7, 3: 0.1}

                    def builder(question):
                        index = int(question["id"].split("-")[1])
                        return {"id": question["id"], "type": "yes_no", "probability": values[index]}

                    return answers_for(body, builder)

                server, endpoint, _ = start_provider(responder)
                try:
                    enable_layer(wiki, endpoint, max_links=1)
                    report = json.loads(
                        wiki.locked(
                            "score_related.py",
                            "--note", "wiki/concepts/netzentgelte.md",
                            "--candidates", "wiki/concepts/bilanzkreis.md,wiki/concepts/redispatch.md,wiki/concepts/messkonzept.md",
                        ).stdout
                    )
                    self.assertEqual(report["state"], "scored")
                    self.assertEqual(report["above_threshold"], 2)
                    self.assertEqual(len(report["links"]), 2)
                    directions = {(link["from"], link["to"]) for link in report["links"]}
                    self.assertIn(("wiki/concepts/bilanzkreis.md", "wiki/concepts/netzentgelte.md"), directions)
                    self.assertIn(("wiki/concepts/netzentgelte.md", "wiki/concepts/bilanzkreis.md"), directions)
                    self.assertIn("page-batch", report["instruction"])
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)

    def test_propose_clusters_assigns_groups_and_flags_uncertain_files(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            os.environ[API_KEY_ENV] = API_KEY_VALUE
            try:
                collection = wiki.root / "collection"
                collection.mkdir()
                (collection / "alpha.md").write_text("# Alpha Dokument\n\nNetzentgelte und Arbeitspreis im Verteilnetz.\n", encoding="utf-8")
                (collection / "beta.md").write_text("# Beta Dokument\n\nEtwas, das zu keinem Cluster passt.\n", encoding="utf-8")
                (collection / "gamma.md").write_text("# Gamma Dokument\n\nUngewisser Inhalt.\n", encoding="utf-8")

                def responder(body: bytes) -> str:
                    request = json.loads(body)
                    state = str(request["state"])

                    def builder(question):
                        if "Titel: Alpha Dokument" in state:
                            probabilities = {"netz": 0.9, "netzbetrieb": 0.05, "none_of_these": 0.05}
                        elif "Titel: Beta Dokument" in state:
                            probabilities = {"netz": 0.05, "netzbetrieb": 0.05, "none_of_these": 0.9}
                        else:
                            probabilities = {"netz": 0.34, "netzbetrieb": 0.33, "none_of_these": 0.33}
                        return {"id": question["id"], "type": "choice", "probabilities": probabilities}

                    return answers_for(body, builder)

                server, endpoint, _ = start_provider(responder)
                try:
                    enable_layer(wiki, endpoint)
                    report = json.loads(
                        wiki.locked(
                            "propose_clusters.py",
                            "--directory", str(collection),
                        ).stdout
                    )
                    self.assertEqual(report["state"], "proposed")
                    assignments = {item["file"]: item["cluster"] for item in report["assignments"]}
                    self.assertEqual(assignments, {"alpha.md": "netz", "beta.md": "new", "gamma.md": "uncertain"})
                    self.assertEqual(report["assigned"], 1)
                    self.assertEqual([c["file"] for c in report["new_candidates"]], ["beta.md"])
                    self.assertEqual(report["uncertain"], ["gamma.md"])
                    self.assertIn("confirm", report["instruction"])
                finally:
                    server.shutdown()
            finally:
                os.environ.pop(API_KEY_ENV, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)

    def test_cluster_folder_above_limit_warns_without_blocking(self) -> None:
        with TempWiki() as wiki:
            Fixture.build(wiki)
            extra = """---
id: "concept-netzbetrieb-steuerung"
title: "Netzbetrieb Steuerung"
type: "concept"
status: "draft"
created: "2026-10-10"
updated: "2026-10-10"
description: "Steuerung des Netzbetriebs."
language: "de"
sources: []
clusters:
  - "netzbetrieb"
concepts: []
tags:
  - "type/wiki-concept"
---

# Netzbetrieb Steuerung

Steuerung des Netzbetriebs.
"""
            wiki.write("wiki/concepts/netzbetrieb/netzbetrieb-steuerung.md", extra)
            index = wiki.read("wiki/index.md").rstrip() + "\n- [[wiki/concepts/netzbetrieb/netzbetrieb-steuerung|Netzbetrieb Steuerung]]\n"
            wiki.write("wiki/index.md", index)
            wiki.rebuild()
            server, endpoint, _ = start_provider(lambda body: "{}")
            try:
                enable_layer(wiki, endpoint, max_notes_per_cluster=1)
                lint = json.loads(wiki.lint().stdout)
                self.assertTrue(lint["valid"], lint["errors"])
                self.assertTrue(
                    any("netzbetrieb" in message and "holds 2 notes" in message for message in lint["warnings"]),
                    lint["warnings"],
                )
            finally:
                server.shutdown()
