#!/usr/bin/env python3
"""A team of maintainers sharing one synchronized wiki (issue #11).

The lock is a directory of per-maintainer claims, so these tests act out what a
SharePoint or OneDrive library actually does to it: a second curator on another
machine, an abandoned run, a conflict copy, a wiki still carrying the old
single-slot lock, and the handover between two of them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintain-llm-wiki" / "scripts"))

import wiki_lock  # noqa: E402
from harness import MAINTAIN, run  # noqa: E402


ALICE = "alice@LAPTOP-ALICE"
BOB = "bob@LAPTOP-BOB"
LOCK = wiki_lock.LOCK_NAME


def lock_tool(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(MAINTAIN / "wiki_lock.py", *args, check=check)


def payload(result: subprocess.CompletedProcess) -> dict:
    """The JSON a helper reported, whether it succeeded or refused."""
    text = result.stdout if result.returncode == 0 else (result.stdout or result.stderr)
    return json.loads(text)


class TeamVault:
    """A bare target directory plus per-maintainer runtime token paths."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="lmwiki-team-")
        self.root = Path(self._temporary.name)
        self.path = self.root / "vault"
        self.path.mkdir()

    def __enter__(self) -> "TeamVault":
        return self

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()

    def token(self, name: str) -> Path:
        return self.root / f"token-{name}"

    def acquire(self, maintainer: str, *extra: str, check: bool = True):
        return lock_tool(
            "acquire",
            "--target", str(self.path),
            "--owner", f"test/{maintainer}",
            "--operation", "maintain",
            "--maintainer", maintainer,
            "--token-file", str(self.token(maintainer)),
            *extra,
            check=check,
        )

    def status(self) -> dict:
        return payload(lock_tool("status", "--target", str(self.path)))

    def claims(self) -> list[Path]:
        directory = self.path / LOCK
        return sorted(directory.glob("claim-*.json")) if directory.is_dir() else []

    def claim_of(self, maintainer: str) -> Path:
        return wiki_lock.claim_path(self.path, maintainer)

    def rewrite(self, path: Path, **changes: object) -> dict:
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update(changes)
        path.write_text(json.dumps(record), encoding="utf-8")
        return record

    def age(self, path: Path, seconds: int) -> None:
        """Make one claim look as old as an abandoned run, clock and file alike."""
        moment = time.time() - seconds
        stamp = wiki_lock.datetime.fromtimestamp(
            moment, wiki_lock.timezone.utc
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.rewrite(path, acquired_at=stamp, heartbeat_at=stamp)
        os.utime(path, (moment, moment))

    def foreign(self, path: Path, host: str) -> None:
        """Mark a claim as written by another machine, as a sync client delivers it."""
        record = self.rewrite(path, host=host)
        moment = wiki_lock.parse_timestamp(record.get("heartbeat_at")) or time.time()
        os.utime(path, (moment, moment))


class OneSlotPerMaintainer(unittest.TestCase):
    def test_each_maintainer_owns_exactly_one_file_and_writes_only_that_one(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            self.assertEqual([path.name for path in vault.claims()],
                             [vault.claim_of(ALICE).name])
            record = json.loads(vault.claim_of(ALICE).read_text(encoding="utf-8"))
            self.assertEqual(record["format"], wiki_lock.CLAIM_FORMAT)
            self.assertEqual(record["maintainer_id"], ALICE)
            self.assertIn("token_sha256", record)

    def test_the_second_maintainer_is_refused_and_told_who_holds_the_wiki(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            refusal = payload(vault.acquire(BOB, check=False))
            self.assertFalse(refusal["acquired"])
            self.assertEqual(refusal["state"], "held")
            self.assertEqual(refusal["lock"]["maintainer_id"], ALICE)
            self.assertNotIn("token_sha256", json.dumps(refusal))

    def test_a_live_run_on_this_machine_is_not_evicted_by_its_own_maintainer(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            first = json.loads(vault.claim_of(ALICE).read_text(encoding="utf-8"))
            refusal = payload(
                lock_tool(
                    "acquire",
                    "--target", str(vault.path),
                    "--owner", "test/second-run",
                    "--maintainer", ALICE,
                    "--token-file", str(vault.token("alice-second")),
                    check=False,
                )
            )
            self.assertFalse(refusal["acquired"])
            self.assertIn("this machine", refusal["error"])
            second = json.loads(vault.claim_of(ALICE).read_text(encoding="utf-8"))
            self.assertEqual(first["claim_id"], second["claim_id"])

    def test_releasing_removes_the_directory_so_readers_stop_seeing_a_busy_wiki(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            self.assertTrue((vault.path / LOCK).is_dir())
            lock_tool(
                "release",
                "--target", str(vault.path),
                "--token-file", str(vault.token(ALICE)),
            )
            self.assertFalse((vault.path / LOCK).exists())
            self.assertEqual(vault.status()["state"], "free")

    def test_operating_system_noise_does_not_keep_the_wiki_busy_forever(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            (vault.path / LOCK / ".DS_Store").write_bytes(b"finder")
            lock_tool(
                "release",
                "--target", str(vault.path),
                "--token-file", str(vault.token(ALICE)),
            )
            self.assertFalse((vault.path / LOCK).exists())


class ConcurrentUse(unittest.TestCase):
    def test_two_effective_claims_stop_every_writer_rather_than_picking_one(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            # What a sync client delivers once both devices are online again:
            # the second claim simply appears, written by the other machine.
            foreign = vault.claim_of(BOB)
            foreign.write_text(
                vault.claim_of(ALICE).read_text(encoding="utf-8"), encoding="utf-8"
            )
            vault.rewrite(
                foreign,
                claim_id="00000000-0000-0000-0000-00000000beef",
                lock_id="00000000-0000-0000-0000-00000000beef",
                maintainer_id=BOB,
                owner="test/bob",
                host="LAPTOP-BOB",
                token_sha256="b" * 64,
            )
            status = vault.status()
            self.assertEqual(status["state"], "contended")
            self.assertEqual(len(status["holders"]), 2)
            self.assertIn("withdraw", status["resolution"])

            token = vault.token(ALICE).read_text(encoding="utf-8").strip()
            refusal = run(
                MAINTAIN / "wiki_lock.py",
                "verify", "--target", str(vault.path), "--lock-token", token,
                check=False,
            )
            self.assertNotEqual(refusal.returncode, 0)
            self.assertEqual(payload(refusal)["state"], "contended")

    def test_a_conflict_copy_of_a_claim_blocks_and_its_owner_can_clear_it(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            original = vault.claim_of(ALICE)
            copy = original.with_name(original.stem + "-DESKTOP-A1B2C3.json")
            copy.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")

            status = vault.status()
            self.assertEqual(status["state"], "contended")
            self.assertEqual(
                [problem["path"] for problem in status["problems"]],
                [f"{LOCK}/{copy.name}"],
            )

            withdrawn = payload(
                lock_tool(
                    "withdraw",
                    "--target", str(vault.path),
                    "--maintainer", ALICE,
                    "--reason", "resolve the conflict copy of my own claim",
                )
            )
            self.assertIn(copy.name, withdrawn["removed"])
            self.assertIn(original.name, withdrawn["removed"])
            self.assertEqual(vault.status()["state"], "free")

    def test_withdraw_never_removes_another_machines_claim(self) -> None:
        with TeamVault() as vault:
            vault.acquire(BOB)
            vault.foreign(vault.claim_of(BOB), "LAPTOP-BOB")
            result = lock_tool(
                "withdraw",
                "--target", str(vault.path),
                "--maintainer", BOB,
                "--reason", "try to clear a teammate",
                check=False,
            )
            report = payload(result)
            self.assertFalse(report["withdrawn"])
            self.assertIn("LAPTOP-BOB", report["refused"][0]["reason"])
            self.assertTrue(vault.claim_of(BOB).is_file())

    def test_a_claim_timestamped_in_the_future_blocks_instead_of_being_guessed_at(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            vault.age(vault.claim_of(ALICE), -7200)
            status = vault.status()
            self.assertEqual(status["state"], "contended")
            self.assertEqual(status["problems"][0]["problem"], "clock_skew")


class Handover(unittest.TestCase):
    def abandoned(self, vault: TeamVault) -> None:
        """Leave a claim from another machine whose lease has long run out."""
        vault.acquire(BOB, "--lease-seconds", "60")
        vault.foreign(vault.claim_of(BOB), "LAPTOP-BOB")
        vault.age(vault.claim_of(BOB), 7200)
        vault.token(BOB).unlink()

    def settle(self, vault: TeamVault, maintainer: str) -> None:
        """Let the declared settle window pass without waiting for it."""
        path = vault.claim_of(maintainer)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["takeover"]["effective_at"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_an_expired_claim_is_not_taken_over_by_age_alone(self) -> None:
        with TeamVault() as vault:
            self.abandoned(vault)
            refusal = payload(vault.acquire(ALICE, check=False))
            self.assertEqual(refusal["state"], "held")
            self.assertTrue(refusal["lock"]["expired"])
            self.assertIn("--take-over", refusal["override_hint"])

    def test_a_takeover_is_declared_first_and_locks_nothing_yet(self) -> None:
        with TeamVault() as vault:
            self.abandoned(vault)
            declared = payload(
                vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave", check=False)
            )
            self.assertEqual(declared["state"], "takeover_declared")
            self.assertFalse(declared["acquired"])
            self.assertFalse(vault.token(ALICE).exists())
            # The declaration carries no token, so it grants nothing by itself.
            record = json.loads(vault.claim_of(ALICE).read_text(encoding="utf-8"))
            self.assertNotIn("token_sha256", record)
            self.assertEqual(vault.status()["lock"]["maintainer_id"], BOB)

    def test_the_settle_window_is_enforced_before_the_handover_completes(self) -> None:
        with TeamVault() as vault:
            self.abandoned(vault)
            vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave", check=False)
            pending = payload(
                vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave", check=False)
            )
            self.assertEqual(pending["state"], "takeover_pending")
            self.assertGreater(pending["seconds_remaining"], 0)

    def test_the_handover_completes_after_the_window_and_supersedes_the_old_claim(self) -> None:
        with TeamVault() as vault:
            self.abandoned(vault)
            vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave", check=False)
            self.settle(vault, ALICE)
            acquired = payload(
                vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave")
            )
            self.assertTrue(acquired["acquired"])
            self.assertEqual(acquired["maintainer_id"], ALICE)
            self.assertEqual(
                acquired["superseded"][0]["maintainer_id"], BOB
            )
            status = vault.status()
            self.assertEqual(status["state"], "held")
            self.assertEqual(status["lock"]["maintainer_id"], ALICE)

    def test_the_superseded_run_is_told_it_was_handed_over_before_it_writes(self) -> None:
        with TeamVault() as vault:
            vault.acquire(BOB, "--lease-seconds", "60")
            bob_token = vault.token(BOB).read_text(encoding="utf-8").strip()
            vault.foreign(vault.claim_of(BOB), "LAPTOP-BOB")
            vault.age(vault.claim_of(BOB), 7200)
            vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave", check=False)
            self.settle(vault, ALICE)
            vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave")

            refusal = run(
                MAINTAIN / "wiki_lock.py",
                "verify", "--target", str(vault.path), "--lock-token", bob_token,
                check=False,
            )
            report = payload(refusal)
            self.assertEqual(report["state"], "superseded")
            self.assertEqual(report["taken_over_by"][0]["maintainer_id"], ALICE)

    def test_a_returning_maintainer_voids_the_declared_takeover(self) -> None:
        with TeamVault() as vault:
            self.abandoned(vault)
            vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave", check=False)
            self.settle(vault, ALICE)
            # Bob's machine comes back and heartbeats once.
            moment = time.time()
            vault.rewrite(vault.claim_of(BOB), heartbeat_at=wiki_lock.utc_now())
            os.utime(vault.claim_of(BOB), (moment, moment))
            voided = payload(
                vault.acquire(ALICE, "--take-over", "--reason", "Bob is on leave", check=False)
            )
            self.assertEqual(voided["state"], "takeover_void")
            self.assertFalse(vault.claim_of(ALICE).exists())
            self.assertEqual(vault.status()["lock"]["maintainer_id"], BOB)

    def test_force_still_overrides_immediately_and_records_what_it_replaced(self) -> None:
        with TeamVault() as vault:
            vault.acquire(BOB)
            vault.foreign(vault.claim_of(BOB), "LAPTOP-BOB")
            acquired = payload(
                vault.acquire(ALICE, "--force", "--reason", "approved by the team lead")
            )
            self.assertTrue(acquired["acquired"])
            self.assertTrue(acquired["forced"])
            self.assertEqual(acquired["superseded"][0]["maintainer_id"], BOB)
            self.assertEqual(vault.status()["lock"]["maintainer_id"], ALICE)

    def test_a_heartbeat_keeps_an_owned_claim_from_expiring(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE, "--lease-seconds", "60")
            vault.age(vault.claim_of(ALICE), 7200)
            report = payload(
                lock_tool(
                    "heartbeat",
                    "--target", str(vault.path),
                    "--token-file", str(vault.token(ALICE)),
                )
            )
            self.assertTrue(report["heartbeat_refreshed"])
            self.assertFalse(vault.status()["lock"]["expired"])


class LegacySingleSlot(unittest.TestCase):
    """A one-person wiki carrying the format-1 lock keeps working unchanged."""

    def legacy(self, vault: TeamVault, token: str = "lk_legacy-token") -> dict:
        record = {
            "format_version": 1,
            "lock_id": "11111111-2222-3333-4444-555555555555",
            "token_sha256": wiki_lock.token_hash(token),
            "owner": "single-maintainer",
            "operation": "maintain",
            "acquired_at": "2026-09-01T08:00:00Z",
            "host": "IMAC-SOLO",
            "forced": False,
        }
        (vault.path / LOCK).write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    def test_the_old_single_file_lock_is_adopted_without_migration(self) -> None:
        with TeamVault() as vault:
            self.legacy(vault)
            status = vault.status()
            self.assertEqual(status["state"], "held")
            self.assertTrue(status["lock"]["legacy_single_slot"])
            self.assertEqual(status["lock"]["owner"], "single-maintainer")
            self.assertEqual(status["foreign_host"], "IMAC-SOLO")

    def test_the_old_lock_never_expires_and_blocks_a_second_maintainer(self) -> None:
        with TeamVault() as vault:
            self.legacy(vault)
            status = vault.status()
            self.assertFalse(status["lock"]["expired"])
            refusal = payload(vault.acquire(ALICE, check=False))
            self.assertEqual(refusal["state"], "held")
            refused_takeover = payload(
                vault.acquire(ALICE, "--take-over", "--reason", "old lock", check=False)
            )
            self.assertEqual(refused_takeover["state"], "held")

    def test_the_old_token_still_releases_the_old_lock(self) -> None:
        with TeamVault() as vault:
            self.legacy(vault, token="lk_legacy-token")
            released = payload(
                lock_tool(
                    "release",
                    "--target", str(vault.path),
                    "--lock-token", "lk_legacy-token",
                )
            )
            self.assertTrue(released["released"])
            self.assertFalse((vault.path / LOCK).exists())
            # The next acquisition uses the team layout; nothing was migrated.
            vault.acquire(ALICE)
            self.assertTrue((vault.path / LOCK).is_dir())

    def test_a_conflict_copy_of_the_old_lock_is_no_longer_invisible(self) -> None:
        with TeamVault() as vault:
            record = self.legacy(vault)
            record["host"] = "LAPTOP-BOB"
            (vault.path / ".llmwiki-DESKTOP-B7K2Q9.lock").write_text(
                json.dumps(record), encoding="utf-8"
            )
            status = vault.status()
            self.assertEqual(status["state"], "contended")
            self.assertEqual(
                status["problems"][0]["path"], ".llmwiki-DESKTOP-B7K2Q9.lock"
            )
            self.assertIn("two machines held it at once", status["problems"][0]["reason"])

    def test_force_clears_the_conflict_copy_and_reports_what_it_held(self) -> None:
        with TeamVault() as vault:
            record = self.legacy(vault)
            record["host"] = "LAPTOP-BOB"
            copy = vault.path / ".llmwiki-DESKTOP-B7K2Q9.lock"
            copy.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(vault.status()["state"], "contended")

            acquired = payload(
                vault.acquire(ALICE, "--force", "--reason", "approved by the team lead")
            )
            self.assertTrue(acquired["acquired"])
            cleared = acquired["cleared_conflict_copies"]
            self.assertEqual(cleared[0]["path"], copy.name)
            self.assertEqual(cleared[0]["content"]["host"], "LAPTOP-BOB")
            self.assertNotIn("token_sha256", json.dumps(cleared))
            self.assertFalse(copy.exists())
            self.assertEqual(vault.status()["state"], "held")

    def test_force_replaces_the_old_lock_with_a_team_claim(self) -> None:
        with TeamVault() as vault:
            self.legacy(vault)
            acquired = payload(
                vault.acquire(ALICE, "--force", "--reason", "approved by the owner")
            )
            self.assertTrue(acquired["acquired"])
            self.assertTrue((vault.path / LOCK).is_dir())
            self.assertEqual(vault.status()["lock"]["maintainer_id"], ALICE)


if __name__ == "__main__":
    unittest.main()
