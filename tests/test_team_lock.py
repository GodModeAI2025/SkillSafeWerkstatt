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


class EvictionIsFinal(unittest.TestCase):
    """An eviction must outlive the claim that performed it.

    Recording "I superseded you" only inside the evicting claim makes the
    eviction as short-lived as that claim: releasing it, or letting it expire,
    handed the wiki straight back to the run that had just been stopped -
    together with a token that still worked.
    """

    def test_a_forced_out_claim_does_not_come_back_when_the_forcer_releases(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            forced = payload(vault.acquire(BOB, "--force", "--reason", "alice is offline"))
            self.assertTrue(forced["acquired"])
            self.assertEqual(
                [entry["maintainer_id"] for entry in forced["overridden_lock"]["evicted_claims"]],
                [ALICE],
            )
            self.assertFalse(vault.claim_of(ALICE).exists())

            released = payload(
                lock_tool("release", "--target", str(vault.path),
                          "--token-file", str(vault.token(BOB)))
            )
            self.assertTrue(released["released"])
            self.assertNotIn("lock_directory_remains", released)
            # The evicted token is dead and the wiki is free, not held by the
            # maintainer who was told to stop.
            self.assertEqual(vault.status()["state"], "free")
            self.assertFalse((vault.path / LOCK).exists())
            refusal = lock_tool("verify", "--target", str(vault.path),
                                "--token-file", str(vault.token(ALICE)), check=False)
            self.assertNotEqual(refusal.returncode, 0)

    def test_a_forced_out_run_is_still_told_precisely_what_happened(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            vault.acquire(BOB, "--force", "--reason", "alice is offline")
            refusal = payload(
                lock_tool("verify", "--target", str(vault.path),
                          "--token-file", str(vault.token(ALICE)), check=False)
            )
            self.assertEqual(refusal["state"], "superseded")
            self.assertEqual([h["maintainer_id"] for h in refusal["taken_over_by"]], [BOB])

    def test_a_handed_over_claim_does_not_come_back_either(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            vault.age(vault.claim_of(ALICE), 4 * 3600 + 2 * 3600)
            vault.acquire(BOB, "--take-over", "--reason", "abandoned", "--settle-seconds", "60",
                          check=False)
            declaration = vault.claim_of(BOB)
            vault.rewrite(declaration, takeover={
                **json.loads(declaration.read_text(encoding="utf-8"))["takeover"],
                "effective_at": "2000-01-01T00:00:00Z",
            })
            taken = payload(
                vault.acquire(BOB, "--take-over", "--reason", "abandoned",
                              "--settle-seconds", "60")
            )
            self.assertTrue(taken["acquired"])
            self.assertFalse(vault.claim_of(ALICE).exists())
            lock_tool("release", "--target", str(vault.path),
                      "--token-file", str(vault.token(BOB)))
            self.assertEqual(vault.status()["state"], "free")


class SimultaneousAcquisition(unittest.TestCase):
    def test_two_processes_racing_never_both_report_success(self) -> None:
        """Two maintainers acquiring in the same moment both used to be told
        "acquired", and only the first helper call found the contention - by
        which time the wiki was stuck until two people ran withdraw. Nothing has
        been written to the wiki yet at that point, so a claim that turns out
        not to be alone is simply taken back, and the collision costs a retry
        instead of two manual repairs."""
        for attempt in range(6):
            with TeamVault() as vault:
                processes = [
                    subprocess.Popen(
                        [sys.executable, str(MAINTAIN / "wiki_lock.py"), "acquire",
                         "--target", str(vault.path),
                         "--owner", f"test/{who}",
                         "--maintainer", who,
                         "--token-file", str(vault.token(who))],
                        cwd=str(MAINTAIN), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True,
                    )
                    for who in (ALICE, BOB)
                ]
                results = [process.communicate() for process in processes]
                winners = [
                    who
                    for who, process in zip((ALICE, BOB), processes)
                    if process.returncode == 0
                ]
                self.assertLessEqual(len(winners), 1, results)
                # Whatever the interleaving was, the wiki is never left in the
                # stop state that only a human could clear.
                self.assertNotEqual(vault.status()["state"], "contended", results)
                for who in (ALICE, BOB):
                    if who not in winners:
                        self.assertFalse(vault.claim_of(who).exists(), results)
                        self.assertFalse(vault.token(who).exists(), results)

    def test_the_wiki_is_left_acquirable_again_afterwards(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            lock_tool("release", "--target", str(vault.path),
                      "--token-file", str(vault.token(ALICE)))
            vault.token(ALICE).unlink(missing_ok=True)
            self.assertTrue(payload(vault.acquire(ALICE))["acquired"])


class ReadersAreNeverLeftBlockedSilently(unittest.TestCase):
    def test_a_release_that_cannot_clear_the_directory_says_so(self) -> None:
        """A crashed atomic write leaves a temporary file in the lock directory.
        Readers judge by the directory alone, so releasing without a word would
        take the wiki offline for the whole team with nothing to go on."""
        with TeamVault() as vault:
            vault.acquire(ALICE)
            (vault.path / LOCK / ".claim-alice.json.abcdef.tmp").write_text("{", encoding="utf-8")
            released = payload(
                lock_tool("release", "--target", str(vault.path),
                          "--token-file", str(vault.token(ALICE)))
            )
            self.assertTrue(released["released"])
            self.assertTrue(released["lock_directory_remains"])
            self.assertIn("wiki_busy", released["reader_warning"])

    def test_status_names_the_directory_that_keeps_readers_out(self) -> None:
        with TeamVault() as vault:
            (vault.path / LOCK).mkdir()
            (vault.path / LOCK / "left-behind.txt").write_text("x", encoding="utf-8")
            status = vault.status()
            self.assertEqual(status["state"], "free")
            self.assertTrue(status["readers_blocked"])


class LockConflictCopyDirectory(unittest.TestCase):
    """The lock is created and removed over and over; that is precisely the
    pattern from which a synchronization client makes a *folder* conflict copy.
    A copy that only files were scanned for hid a whole second set of claims."""

    def conflicted(self, vault: "TeamVault") -> Path:
        copy = vault.path / ".llmwiki-DESKTOP-B7K2Q9.lock"
        copy.mkdir()
        (copy / f"{wiki_lock.CLAIM_PREFIX}bob{wiki_lock.CLAIM_SUFFIX}").write_text(
            json.dumps({
                "format": wiki_lock.CLAIM_FORMAT,
                "format_version": 2,
                "claim_id": "from-the-other-device",
                "maintainer_id": BOB,
                "owner": "test/bob",
                "acquired_at": wiki_lock.utc_now(),
                "heartbeat_at": wiki_lock.utc_now(),
                "lease_seconds": 3600,
                "host": "LAPTOP-BOB",
                "token_sha256": wiki_lock.token_hash("lk_bob"),
            }),
            encoding="utf-8",
        )
        return copy

    def test_a_conflicted_lock_directory_is_reported_and_blocks_every_writer(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            copy = self.conflicted(vault)
            status = vault.status()
            self.assertEqual(status["state"], "contended")
            problem = next(entry for entry in status["problems"] if entry["path"] == copy.name)
            self.assertTrue(problem["directory"])
            self.assertEqual(problem["contains"], [f"{wiki_lock.CLAIM_PREFIX}bob{wiki_lock.CLAIM_SUFFIX}"])
            refusal = payload(
                lock_tool("verify", "--target", str(vault.path),
                          "--token-file", str(vault.token(ALICE)), check=False)
            )
            self.assertEqual(refusal["state"], "contended")

    def test_force_clears_it_and_reports_every_claim_it_contained(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            copy = self.conflicted(vault)
            acquired = payload(
                vault.acquire(BOB, "--force", "--reason", "agreed with the team")
            )
            self.assertTrue(acquired["acquired"])
            cleared = next(
                entry for entry in acquired["cleared_conflict_copies"]
                if entry["path"] == copy.name
            )
            self.assertTrue(cleared["directory"])
            self.assertEqual(cleared["contained"][0]["content"]["maintainer_id"], BOB)
            self.assertNotIn("token_sha256", json.dumps(cleared))
            self.assertFalse(copy.exists())
            self.assertEqual(vault.status()["state"], "held")


class ClocksThatDisagree(unittest.TestCase):
    def test_a_maintainer_whose_clock_runs_behind_still_cancels_a_takeover(self) -> None:
        """A host running hours behind writes heartbeats that keep looking old
        here, so "expired" alone would evict somebody who is plainly working.
        Movement of the recorded stamp cannot be faked away by a wrong clock."""
        with TeamVault() as vault:
            vault.acquire(ALICE)
            vault.age(vault.claim_of(ALICE), 3 * 3600)
            declared = payload(
                vault.acquire(BOB, "--take-over", "--reason", "looks abandoned",
                              "--settle-seconds", "60", check=False)
            )
            self.assertEqual(declared["state"], "takeover_declared")

            # Alice works on: her heartbeat advances, but her clock keeps it in
            # the past, so she still looks expired to Bob's machine.
            lock_tool("heartbeat", "--target", str(vault.path),
                      "--token-file", str(vault.token(ALICE)))
            vault.age(vault.claim_of(ALICE), 3 * 3600 - 5)

            declaration = vault.claim_of(BOB)
            vault.rewrite(declaration, takeover={
                **json.loads(declaration.read_text(encoding="utf-8"))["takeover"],
                "effective_at": "2000-01-01T00:00:00Z",
            })
            refusal = payload(
                vault.acquire(BOB, "--take-over", "--reason", "looks abandoned",
                              "--settle-seconds", "60", check=False)
            )
            self.assertEqual(refusal["state"], "takeover_void")
            self.assertEqual([c["maintainer_id"] for c in refusal["returned"]], [ALICE])
            self.assertTrue(payload(
                lock_tool("verify", "--target", str(vault.path),
                          "--token-file", str(vault.token(ALICE)))
            )["owned"])

    def test_the_maintainer_a_takeover_targets_is_told_by_the_call_they_run(self) -> None:
        with TeamVault() as vault:
            vault.acquire(ALICE)
            vault.age(vault.claim_of(ALICE), 3 * 3600)
            vault.acquire(BOB, "--take-over", "--reason", "looks abandoned",
                          "--settle-seconds", "60", check=False)
            beat = payload(
                lock_tool("heartbeat", "--target", str(vault.path),
                          "--token-file", str(vault.token(ALICE)))
            )
            self.assertEqual(
                [c["maintainer_id"] for c in beat["takeover_declared_against_this_claim"]],
                [BOB],
            )
            self.assertIn("declared a takeover", beat["takeover_notice"])


if __name__ == "__main__":
    unittest.main()
