#!/usr/bin/env python3
"""Retry behaviour, storage hints, and honest lock reporting (S1d, S1e)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import portable_io  # noqa: E402
import sync_artifacts  # noqa: E402
from harness import TempWiki  # noqa: E402


class RetryBehaviour(unittest.TestCase):
    def test_a_transient_sharing_violation_is_retried_and_succeeds(self) -> None:
        attempts = {"count": 0}

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise PermissionError(13, "held by another process")
            return "done"

        self.assertEqual(portable_io.with_retry(flaky, what="test"), "done")
        self.assertEqual(attempts["count"], 3)

    def test_a_persistent_violation_reports_the_likely_cause(self) -> None:
        def always() -> str:
            raise PermissionError(13, "held forever")

        with self.assertRaises(portable_io.TransientStorageError) as caught:
            portable_io.with_retry(always, what="replacing manifest.json")
        message = str(caught.exception)
        self.assertIn("replacing manifest.json", message)
        self.assertIn("synchronization client", message)

    def test_a_real_error_is_not_retried(self) -> None:
        attempts = {"count": 0}

        def missing() -> str:
            attempts["count"] += 1
            raise FileNotFoundError(2, "no such file")

        with self.assertRaises(FileNotFoundError):
            portable_io.with_retry(missing, what="test")
        self.assertEqual(attempts["count"], 1, "a missing file must fail immediately")

    def test_atomic_write_leaves_no_temporary_behind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.json"
            portable_io.atomic_write_text(path, '{"a": 1}\n')
            self.assertEqual(path.read_text(encoding="utf-8"), '{"a": 1}\n')
            self.assertEqual(
                [item.name for item in Path(directory).iterdir()],
                ["out.json"],
                "the temporary file must not survive a successful write",
            )


class StorageHint(unittest.TestCase):
    def test_an_ordinary_path_is_not_flagged(self) -> None:
        hint = sync_artifacts.storage_hint(Path("/tmp/plain-wiki"), environment={})
        self.assertFalse(hint["synchronized"])
        self.assertEqual(hint["advisory"], "")

    def test_a_onedrive_path_component_is_flagged(self) -> None:
        hint = sync_artifacts.storage_hint(
            Path("/Users/max/OneDrive - Contoso/Wiki"), environment={}
        )
        self.assertTrue(hint["synchronized"])
        self.assertIn("cooperative file lock", hint["advisory"])

    def test_the_hint_is_labelled_as_a_heuristic(self) -> None:
        hint = sync_artifacts.storage_hint(Path("/x/SharePoint/w"), environment={})
        self.assertEqual(
            hint["confidence"],
            "heuristic",
            "the skill must not present a guess about the storage as a fact",
        )

    def test_the_environment_variable_is_honoured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cloud"
            inner = root / "team" / "wiki"
            inner.mkdir(parents=True)
            hint = sync_artifacts.storage_hint(inner, environment={"OneDrive": str(root)})
            self.assertTrue(hint["synchronized"])


class LockHonesty(unittest.TestCase):
    def test_a_lock_from_another_machine_is_disclosed(self) -> None:
        with TempWiki() as wiki:
            token_file = wiki.root / "token"
            wiki.maintain(
                "wiki_lock.py", "acquire",
                "--target", str(wiki.path),
                "--token-file", str(token_file),
                "--owner", "test/holder",
            )
            try:
                # Simulate the record a second device would have written.
                lock_path = wiki.path / ".llmwiki.lock"
                record = json.loads(lock_path.read_text(encoding="utf-8"))
                record["host"] = "OTHER-MACHINE"
                lock_path.write_text(json.dumps(record), encoding="utf-8")

                status = json.loads(
                    wiki.maintain(
                        "wiki_lock.py", "status", "--target", str(wiki.path)
                    ).stdout
                )
                self.assertEqual(status["foreign_host"], "OTHER-MACHINE")
                self.assertIn("age", status["note"], status["note"])
            finally:
                (wiki.path / ".llmwiki.lock").unlink(missing_ok=True)

    def test_a_local_lock_is_not_flagged_as_foreign(self) -> None:
        with TempWiki() as wiki:
            token_file = wiki.root / "token"
            wiki.maintain(
                "wiki_lock.py", "acquire",
                "--target", str(wiki.path),
                "--token-file", str(token_file),
                "--owner", "test/holder",
            )
            try:
                status = json.loads(
                    wiki.maintain(
                        "wiki_lock.py", "status", "--target", str(wiki.path)
                    ).stdout
                )
                self.assertNotIn("foreign_host", status)
            finally:
                wiki.maintain(
                    "wiki_lock.py", "release",
                    "--target", str(wiki.path),
                    "--token-file", str(token_file),
                    check=False,
                )

    def test_the_private_token_never_reaches_standard_output(self) -> None:
        with TempWiki() as wiki:
            token_file = wiki.root / "token"
            result = wiki.maintain(
                "wiki_lock.py", "acquire",
                "--target", str(wiki.path),
                "--token-file", str(token_file),
                "--owner", "test/holder",
            )
            token = token_file.read_text(encoding="utf-8").strip()
            try:
                self.assertNotIn(token, result.stdout)
                self.assertNotIn(token, result.stderr)
                status = wiki.maintain(
                    "wiki_lock.py", "status", "--target", str(wiki.path)
                ).stdout
                self.assertNotIn(token, status)
            finally:
                wiki.maintain(
                    "wiki_lock.py", "release",
                    "--target", str(wiki.path),
                    "--token-file", str(token_file),
                    check=False,
                )



class HydrationGate(unittest.TestCase):
    """S2a: measure what verification would download before paying for it."""

    def test_a_local_wiki_needs_no_hydration(self) -> None:
        with TempWiki() as wiki:
            state = wiki.verify()
            self.assertEqual(state["state"], "ready")

    def test_detection_reads_only_metadata(self) -> None:
        with TempWiki() as wiki:
            report = sync_artifacts.hydration_report(
                wiki.path, ["wiki/index.md", "wiki/overview.md"]
            )
            self.assertEqual(report["dataless"], 0)
            self.assertEqual(report["inspected"], 2)
            self.assertIn("nothing was hydrated", report["method"])

    def test_a_missing_file_is_undetermined_not_dataless(self) -> None:
        with TempWiki() as wiki:
            report = sync_artifacts.hydration_report(wiki.path, ["wiki/does-not-exist.md"])
            self.assertEqual(report["dataless"], 0)
            self.assertEqual(report["undetermined"], 1)

    def test_a_sparse_file_is_recognised_as_dataless(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sparse = root / "placeholder.md"
            # A file that reports a size but occupies no blocks is exactly the
            # shape Files On-Demand leaves behind.
            with open(sparse, "wb") as handle:
                handle.truncate(4096)
            state = sync_artifacts.is_dataless(sparse)
            if state is None:
                self.skipTest("this platform exposes no usable dataless signal")
            self.assertTrue(state, "a size without blocks must count as dataless")

    def test_verification_stops_before_downloading_the_wiki(self) -> None:
        with TempWiki() as wiki:
            manifest = json.loads(wiki.read("meta/manifest.json"))
            victim = manifest["files"][0]["path"]
            # Replace one released file with a dataless placeholder of equal size.
            path = wiki.path / victim
            size = path.stat().st_size
            path.unlink()
            with open(path, "wb") as handle:
                handle.truncate(size)
            if sync_artifacts.is_dataless(path) is not True:
                self.skipTest("this platform exposes no usable dataless signal")
            state = wiki.verify()
            self.assertEqual(state["state"], "hydration_required")
            self.assertGreaterEqual(state["hydration"]["dataless"], 1)
            self.assertIn("offline", state["reason"])


class HonestPersistence(unittest.TestCase):
    """S2c: a durable local write is not an upload."""

    def test_a_local_release_claims_only_local_durability(self) -> None:
        with TempWiki() as wiki:
            payload = json.loads(wiki.release("persist-local").stdout)
            self.assertEqual(payload["persistence"]["remote"], "not-applicable")

    def test_a_synchronized_release_never_claims_the_upload_happened(self) -> None:
        import release_wiki

        statement = release_wiki.persistence_statement(Path("/Users/x/OneDrive - Contoso/wiki"))
        self.assertEqual(statement["remote"], "unconfirmed")
        self.assertIn("do not tell others", statement["statement"])
if __name__ == "__main__":
    unittest.main(verbosity=2)


class StoragePathProfile(unittest.TestCase):
    """S3: a wiki that could never sync must be refused before it is created."""

    def _initialize(self, prefix: str):
        import shutil as _shutil
        import tempfile as _tempfile

        import harness
        from harness import MAINTAIN, run, run_json

        directory = Path(_tempfile.mkdtemp(prefix="lmwiki-prefix-"))
        self.addCleanup(_shutil.rmtree, directory, True)
        (directory / "i.json").write_text(json.dumps(harness.IDENTITY), encoding="utf-8")
        plan = run_json(
            MAINTAIN / "plan_identity.py",
            "--input", str(directory / "i.json"),
            "--output", str(directory / "p.json"),
        )
        result = run(
            MAINTAIN / "initialize_wiki.py",
            "--target", str(directory / "w"),
            "--title", "T", "--topic", "X", "--wiki-language", "de",
            "--storage-path-prefix", prefix,
            "--identity-plan", str(directory / "p.json"),
            "--expect-identity-sha256", plan["proposal_sha256"],
            "--owner", "test/prefix",
            check=False,
        )
        return directory, json.loads(result.stdout)

    def test_a_realistic_library_path_initializes_normally(self) -> None:
        directory, payload = self._initialize("sites/Team/Dokumente/Wiki")
        self.assertEqual(payload["state"], "initialized", payload)
        profile = (directory / "w" / "schema" / "WIKI_PROFILE.md").read_text(encoding="utf-8")
        self.assertIn('storage_path_prefix: "sites/Team/Dokumente/Wiki"', profile)

    def test_a_prefix_that_makes_every_path_too_long_is_refused(self) -> None:
        _, payload = self._initialize("sites/Team/" + "x" * 380)
        self.assertEqual(payload["state"], "initialization_failed")
        self.assertFalse(payload["partial_state_preserved"])

    def test_the_failure_names_the_actual_reason(self) -> None:
        _, payload = self._initialize("sites/Team/" + "x" * 380)
        self.assertIn(
            "400-character",
            payload["error"],
            "a failed initialization must say why, not return a JSON fragment",
        )

    def test_no_prefix_leaves_the_limits_unchecked(self) -> None:
        directory, payload = self._initialize("")
        self.assertEqual(payload["state"], "initialized")
        profile = (directory / "w" / "schema" / "WIKI_PROFILE.md").read_text(encoding="utf-8")
        self.assertIn('storage_path_prefix: ""', profile)
if __name__ == "__main__":
    unittest.main(verbosity=2)
