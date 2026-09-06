#!/usr/bin/env python3
"""Record who confirmed individual wiki pages, as a hash-bound transaction.

A wiki-wide quality review says when someone last looked at the wiki. It cannot
say which pages that covered. This helper records a confirmation on the pages it
actually applies to, so the read skill can disclose the trust tier of the pages
an answer rests on.

Recording a human review is deliberately harder than recording a machine one: a
`human:` actor requires a separate confirmation argument, because an agent must
never be able to mark its own output as read by a person.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

import portable_io
import trust_contract
from frontmatter_contract import FrontmatterError, compose_document, parse_file
from snapshot_wiki import create_snapshot
from wiki_lock import require_lock


PLAN_FORMAT = "lmwiki-verification-plan/1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def portable_page(value: str) -> bool:
    posix = PurePosixPath(value)
    return (
        bool(value)
        and value == posix.as_posix()
        and value.startswith("wiki/")
        and value.endswith(".md")
        and not posix.is_absolute()
        and ".." not in posix.parts
        and "\\" not in value
    )


def build_plan(target: Path, relatives: list[str], actor: str, at: str) -> dict[str, object]:
    if not trust_contract.valid_actor(actor):
        raise SystemExit(f"actor must be agent/<name>, human:<id>, or process:<id>, not {actor!r}")
    entries = []
    for relative in relatives:
        if not portable_page(relative):
            raise SystemExit(f"not a portable wiki page path: {relative!r}")
        path = target / relative
        if not path.is_file():
            raise SystemExit(f"page does not exist: {relative}")
        try:
            document = parse_file(path, require_frontmatter=True)
        except (OSError, UnicodeError, FrontmatterError) as exc:
            raise SystemExit(f"{relative}: {exc}") from exc
        if document.data.get("type") == "index":
            raise SystemExit(f"{relative}: an index carries no assertions to confirm")
        before = trust_contract.trust_tier(document.data)
        after = trust_contract.trust_tier({trust_contract.VERIFIED_BY: actor})
        entries.append(
            {
                "path": relative,
                "before_sha256": sha256_bytes(path.read_bytes()),
                "tier_before": before,
                "tier_after": after,
                "previous_verified_by": str(document.data.get(trust_contract.VERIFIED_BY) or ""),
                "previous_verified_at": str(document.data.get(trust_contract.VERIFIED_AT) or ""),
            }
        )
    payload = {
        "format": PLAN_FORMAT,
        "actor": actor,
        "verified_at": at,
        "human_review": trust_contract.is_human(actor),
        "pages": entries,
        "boundary": (
            "Recording a confirmation states who looked and when. It does not make the page "
            "correct, and it does not replace the wiki-wide quality review."
        ),
    }
    return {**payload, "plan_sha256": sha256_bytes(canonical(payload))}


def validate_plan(plan: object, expected: str) -> dict[str, object]:
    if not isinstance(plan, dict) or plan.get("format") != PLAN_FORMAT:
        raise SystemExit("unsupported verification plan")
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if not expected or plan.get("plan_sha256") != expected or sha256_bytes(canonical(payload)) != expected:
        raise SystemExit("verification plan is stale or was modified after confirmation")
    return plan


def apply_plan(target: Path, token: str, plan: dict[str, object]) -> tuple[dict[str, object], int]:
    actor = str(plan["actor"])
    at = str(plan["verified_at"])
    pages = list(plan["pages"])  # type: ignore[arg-type]

    # Re-check every precondition before the first write, so a plan that no
    # longer matches the wiki performs zero writes.
    for entry in pages:
        path = target / str(entry["path"])
        if not path.is_file() or sha256_bytes(path.read_bytes()) != entry["before_sha256"]:
            return {
                "state": "stale_plan",
                "reason": f"page changed after the plan was built: {entry['path']}",
                "writes": 0,
            }, 3

    snapshot = create_snapshot(
        target,
        token,
        operation="verify-pages",
        selected_files=[str(entry["path"]) for entry in pages],
    )

    written = []
    for entry in pages:
        relative = str(entry["path"])
        path = target / relative
        document = parse_file(path, require_frontmatter=True)
        data = dict(document.data)
        data[trust_contract.VERIFIED_BY] = actor
        data[trust_contract.VERIFIED_AT] = at
        portable_io.atomic_write_text(path, compose_document(document, data))
        written.append({"path": relative, "tier": trust_contract.trust_tier(data)})

    return (
        {
            "state": "applied",
            "actor": actor,
            "verified_at": at,
            "writes": len(written),
            "snapshot": snapshot,
            "pages": written,
            "next_steps": [
                "Rebuild the graph and reading views.",
                "Run the strict linter.",
                "Publish a release so the trust distribution reaches readers.",
            ],
        },
        0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="Show what a confirmation would record")
    plan_parser.add_argument("--target", required=True)
    plan_parser.add_argument("--lock-token", required=True)
    plan_parser.add_argument("--actor", required=True, help="agent/<name>, human:<id>, or process:<id>")
    plan_parser.add_argument("--page", action="append", required=True, dest="pages")
    plan_parser.add_argument("--output")
    apply_parser = subparsers.add_parser("apply", help="Apply one confirmed verification plan")
    apply_parser.add_argument("--target", required=True)
    apply_parser.add_argument("--lock-token", required=True)
    apply_parser.add_argument("--plan-file", required=True)
    apply_parser.add_argument("--expect-plan-sha256", required=True)
    apply_parser.add_argument(
        "--user-confirmed-human-review",
        action="store_true",
        help=(
            "Required for a human: actor. Pass it only after the person named actually "
            "confirmed they reviewed these pages."
        ),
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")

    if args.command == "plan":
        plan = build_plan(target, list(args.pages), args.actor, trust_contract.utc_now())
        if args.output:
            output = Path(args.output).expanduser().resolve()
            if output == target or target in output.parents:
                raise SystemExit("the plan must stay outside the target wiki")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    plan = validate_plan(
        json.loads(Path(args.plan_file).read_text(encoding="utf-8")),
        args.expect_plan_sha256,
    )
    # An agent must never be able to record a human review on its own authority.
    if plan.get("human_review") and not args.user_confirmed_human_review:
        print(
            json.dumps(
                {
                    "state": "confirmation_required",
                    "writes": 0,
                    "reason": (
                        "This plan records a human review. Re-run with "
                        "--user-confirmed-human-review only after the named person confirmed "
                        "they reviewed these pages."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    result, code = apply_plan(target, args.lock_token, plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
