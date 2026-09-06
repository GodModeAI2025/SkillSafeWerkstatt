#!/usr/bin/env python3
"""Plan and apply the resolution of synchronization conflict copies.

A OneDrive or SharePoint client never merges. When two devices changed the same
file, it keeps both and renames one after the device. The copy may hold work
nobody else has, so it is never removed silently: this helper shows both sides,
takes a hash-bound decision from the user, snapshots first, and only then acts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import portable_io
import sync_artifacts
from snapshot_wiki import create_snapshot
from wiki_lock import require_lock


PLAN_FORMAT = "lmwiki-conflict-resolution/1"
SCANNED_DIRS = ("schema", "sources", "wiki", "graph")

#: What the user may decide for one conflict copy.
DECISIONS = {
    "keep-original": "Discard the copy and keep the released file unchanged.",
    "keep-copy": "Replace the original with the copy's content.",
    "keep-both": "Rename the copy to a clean name so both can be curated.",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def describe(target: Path, relative: str) -> dict[str, object]:
    path = target / relative
    try:
        content = path.read_bytes()
    except OSError:
        return {"path": relative, "exists": False}
    stat = path.stat()
    return {
        "path": relative,
        "exists": True,
        "sha256": sha256_bytes(content),
        "bytes": len(content),
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }


def clean_name(relative: str) -> str:
    """Derive a storage-safe name for a copy the user wants to keep."""
    path = Path(relative)
    artifact = sync_artifacts.classify(relative)
    base = Path(artifact.original).stem if artifact and artifact.original else path.stem
    candidate = f"{base}-konflikt{path.suffix}"
    return (path.parent / candidate).as_posix()


def build_plan(target: Path) -> dict[str, object]:
    relatives = sync_artifacts.walk(target, SCANNED_DIRS)
    conflicts = [
        artifact
        for artifact in sync_artifacts.classify_all(relatives)
        if artifact.kind == sync_artifacts.CONFLICT_COPY
    ]
    entries = []
    for artifact in conflicts:
        copy = describe(target, artifact.path)
        original = describe(target, artifact.original)
        identical = (
            bool(copy.get("exists"))
            and bool(original.get("exists"))
            and copy.get("sha256") == original.get("sha256")
        )
        entries.append(
            {
                "copy": copy,
                "original": original,
                "identical": identical,
                "suggested_clean_name": clean_name(artifact.path),
                # An identical copy carries nothing new, so discarding it loses
                # nothing. Anything else is a real decision for the user.
                "recommended": "keep-original" if identical else "",
            }
        )
    payload = {"format": PLAN_FORMAT, "target": ".", "conflicts": entries}
    return {**payload, "plan_sha256": sha256_bytes(canonical(payload))}


def validate_plan(plan: object, expected: str) -> dict[str, object]:
    if not isinstance(plan, dict) or plan.get("format") != PLAN_FORMAT:
        raise SystemExit("unsupported conflict resolution plan")
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    actual = sha256_bytes(canonical(payload))
    if not expected or plan.get("plan_sha256") != expected or actual != expected:
        raise SystemExit("conflict resolution plan is stale or was modified after confirmation")
    return plan


def parse_decisions(values: list[str]) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for raw in values:
        relative, separator, choice = raw.partition("=")
        if not separator or choice not in DECISIONS:
            raise SystemExit(
                f"invalid decision {raw!r}; use <path>=<{'|'.join(sorted(DECISIONS))}>"
            )
        if relative in decisions:
            raise SystemExit(f"duplicate decision for {relative}")
        decisions[relative] = choice
    return decisions


def apply_plan(
    target: Path,
    token: str,
    plan: dict[str, object],
    decisions: dict[str, str],
) -> tuple[dict[str, object], int]:
    conflicts = {str(entry["copy"]["path"]): entry for entry in plan["conflicts"]}  # type: ignore[index]
    unknown = sorted(set(decisions) - set(conflicts))
    if unknown:
        return {"state": "invalid_decision", "unknown_paths": unknown, "writes": 0}, 2
    undecided = sorted(set(conflicts) - set(decisions))
    if undecided:
        return {"state": "decision_required", "undecided": undecided, "writes": 0}, 2

    # Re-check every precondition immediately before writing, so a plan that has
    # gone stale performs zero writes rather than a partial resolution.
    for relative, entry in conflicts.items():
        if describe(target, relative) != entry["copy"]:
            return {"state": "stale_plan", "reason": f"conflict copy changed: {relative}", "writes": 0}, 3
        original = str(entry["original"]["path"])  # type: ignore[index]
        if describe(target, original) != entry["original"]:
            return {"state": "stale_plan", "reason": f"original changed: {original}", "writes": 0}, 3

    if not conflicts:
        return {"state": "nothing_to_do", "writes": 0}, 0

    affected = sorted(
        {relative for relative in conflicts}
        | {str(entry["original"]["path"]) for entry in conflicts.values()}  # type: ignore[index]
    )
    snapshot = create_snapshot(
        target,
        token,
        operation="resolve-conflict-copy",
        selected_files=[path for path in affected if (target / path).is_file()],
    )

    actions = []
    for relative, entry in sorted(conflicts.items()):
        choice = decisions[relative]
        copy_path = target / relative
        original_relative = str(entry["original"]["path"])  # type: ignore[index]
        original_path = target / original_relative
        if choice == "keep-original":
            copy_path.unlink()
            actions.append({"path": relative, "decision": choice, "result": "copy removed"})
        elif choice == "keep-copy":
            portable_io.atomic_write_bytes(original_path, copy_path.read_bytes())
            copy_path.unlink()
            actions.append(
                {"path": relative, "decision": choice, "result": f"{original_relative} replaced"}
            )
        else:
            destination = target / str(entry["suggested_clean_name"])
            if destination.exists():
                return {
                    "state": "target_exists",
                    "reason": f"{destination.relative_to(target).as_posix()} already exists",
                    "writes": 0,
                    "snapshot": snapshot,
                }, 4
            portable_io.replace_with_retry(copy_path, destination)
            actions.append(
                {
                    "path": relative,
                    "decision": choice,
                    "result": f"renamed to {destination.relative_to(target).as_posix()}",
                }
            )
    return (
        {
            "state": "applied",
            "writes": len(actions),
            "snapshot": snapshot,
            "actions": actions,
            "next_steps": next_steps(actions),
        },
        0,
    )


def next_steps(actions: list[dict[str, str]]) -> list[str]:
    """Say what still has to happen, including work a decision created."""
    steps = []
    if any(action["decision"] == "keep-both" for action in actions):
        # A renamed copy is a new page: unlisted, unlinked, and without its own
        # claims, so the linter will reject a release until it is curated.
        steps.append(
            "Curate each renamed copy as a real page: give it its own id, list it in "
            "wiki/index.md, and check its claims. Until then the linter will refuse a release."
        )
    steps.extend(
        [
            "Rebuild the graph and reading views.",
            "Run the strict linter.",
            "Publish a new release so readers see one consistent state.",
        ]
    )
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="Report conflict copies without changing anything")
    plan_parser.add_argument("--target", required=True)
    plan_parser.add_argument("--lock-token", required=True)
    plan_parser.add_argument("--output")
    apply_parser = subparsers.add_parser("apply", help="Apply one confirmed resolution plan")
    apply_parser.add_argument("--target", required=True)
    apply_parser.add_argument("--lock-token", required=True)
    apply_parser.add_argument("--plan-file", required=True)
    apply_parser.add_argument("--expect-plan-sha256", required=True)
    apply_parser.add_argument(
        "--decision",
        action="append",
        default=[],
        metavar="PATH=CHOICE",
        help=f"One decision per conflict copy: {', '.join(sorted(DECISIONS))}",
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    require_lock(target, args.lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")

    if args.command == "plan":
        plan = build_plan(target)
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
    result, code = apply_plan(target, args.lock_token, plan, parse_decisions(args.decision))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
