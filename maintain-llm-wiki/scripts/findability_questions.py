#!/usr/bin/env python3
"""Record, remove, and check findability questions in the owner's or users' own words.

A findability question is a wording the wiki's owner or a user supplied,
together with the claim that answers it. `check` ranks every question with the
query skill's search core on the working files and reports which ones no
longer bring their target claim back. Questions written by the maintaining
agent with the page open pass by construction and measure nothing, so `add`
requires `--user-supplied-wording`, an attestation the helper cannot verify.

The questions live in `meta/findability-questions.jsonl`, outside the release:
it is never hashed into the manifest, verified, included in the default
snapshot, or exported, and the query skill never reads it. Outside the release
is not private: anyone with access to the wiki folder can read the file. The
check never blocks a release.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Siblings are imported from this folder even where the interpreter leaves it
# off sys.path: python -I, python -P, PYTHONSAFEPATH=1.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import portable_io
import search_core
import secret_screen
import sync_artifacts
from frontmatter_contract import FrontmatterError
from snapshot_wiki import create_snapshot
from wiki_lock import require_lock


RELATIVE = "meta/findability-questions.jsonl"
RECORD_FORMAT = "lmwiki-findability-question/1"
REPORT_FORMAT = "lmwiki-findability-report/1"
#: The most questions a file holds, so one check stays fast.
MAX_QUESTIONS = 200
MAX_QUESTION_CHARS = 500
MAX_NOTE_CHARS = 200
DEFAULT_LIMIT = 12
AUTHORS = ("owner", "user")
RECORD_KEYS = frozenset({"format", "question_id", "question", "claim_id", "author", "note", "added_at", "lock_id"})
QUESTION_ID = re.compile(r"^fq-[0-9a-f]{16}$")
#: Characters `str.splitlines` treats as line ends but `json.dumps(ensure_ascii=False)` leaves raw.
LINE_SEPARATORS = {"\u0085": "\\u0085", "\u2028": "\\u2028", "\u2029": "\\u2029"}
CLAIM_ID = re.compile(r"^clm-[0-9a-f]{16}$")
TARGET_STATUSES = frozenset({"active", "disputed"})
STATUSES = ("found", "found_page_only", "not_found", "target_missing", "target_inactive")
PARSER_REFUSAL = (
    "the wiki has pages outside the frontmatter contract; run lint and repair them before {what}"
)
BOUNDARY = (
    "These questions were recorded as the owner's or users' own words; the helper cannot verify that. They were "
    "searched on the working files under the maintenance lock with the query skill's search core. A question "
    "counts as found when its target claim comes back among the claims of a result within the limit. A pass does "
    "not show that other wordings succeed, and a failure does not show that the fact is missing from the wiki."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def refuse_conflict_copies(target: Path) -> None:
    """Stop when the synchronization client kept a second version of the questions file."""
    meta = target / "meta"
    if not meta.is_dir():
        return
    for path in sorted(meta.iterdir()):
        if not path.is_file():
            continue
        artifact = sync_artifacts.classify(f"meta/{path.name}")
        if artifact is not None and artifact.kind == sync_artifacts.CONFLICT_COPY and artifact.original == RELATIVE:
            raise SystemExit(
                f"{RELATIVE} has a synchronization conflict copy (meta/{path.name}); merge the two files with "
                "the user before recording or checking questions"
            )


def record_problem(record: Any, seen: set[str]) -> Optional[str]:
    """What is wrong with one parsed line, or None."""
    if not isinstance(record, dict) or record.get("format") != RECORD_FORMAT:
        return "unsupported record format"
    for key in sorted(record):
        if key not in RECORD_KEYS:
            return f"unknown key '{key}'"
    question_id = record.get("question_id")
    if not isinstance(question_id, str) or not QUESTION_ID.match(question_id) or question_id in seen:
        return "invalid or duplicate question_id"
    question = record.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS:
        return "invalid question"
    if not isinstance(record.get("claim_id"), str) or not CLAIM_ID.match(record["claim_id"]):
        return "invalid claim_id"
    if record.get("author") not in AUTHORS:
        return "invalid author"
    if not valid_timestamp(record.get("added_at")):
        return "invalid added_at"
    note = record.get("note", "")
    if not isinstance(note, str) or len(note) > MAX_NOTE_CHARS or "\n" in note or "\r" in note:
        return "invalid note"
    if not isinstance(record.get("lock_id", ""), str):
        return "invalid lock_id"
    return None


def read_questions(target: Path) -> list[dict[str, Any]]:
    """Every question of the file in file order; refuses a file with any invalid line, naming it."""
    path = target / RELATIVE
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise SystemExit(f"{RELATIVE}: not UTF-8 text: {exc}") from exc
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Only "\n" ends a record: splitlines() would also cut at U+2028 inside a question.
    for number, line in enumerate(text.split("\n"), 1):
        line = line.removesuffix("\r")
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            raise SystemExit(f"{RELATIVE}:{number}: invalid JSON") from None
        problem = record_problem(record, seen)
        if problem:
            raise SystemExit(f"{RELATIVE}:{number}: {problem}")
        seen.add(record["question_id"])
        records.append(record)
    return records


def write_questions(target: Path, records: list[dict[str, Any]]) -> None:
    lines = []
    for record in records:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        for character, escape in LINE_SEPARATORS.items():
            line = line.replace(character, escape)
        lines.append(line + "\n")
    portable_io.atomic_write_bytes(target / RELATIVE, "".join(lines).encode("utf-8"))


def question_from_input(value: str, stdin: Any) -> str:
    """The wording from --question, or from one {"query": ...} object on standard input for `-`."""
    if value != "-":
        return value
    try:
        # Verbatim: a real "?" before a letter ("kündigen?danke") arrives as \u003f.
        request = search_core.request_from_stdin(stdin, verbatim=True)
    except search_core.RequestError as exc:
        detail = str(exc).removeprefix("request is invalid: ").replace("--request -", "--question -")
        raise SystemExit(f"question input is invalid: {detail}") from None
    if request["also"] or request["filter"] is not None:
        raise SystemExit('a findability question is one wording; send only {"query": ...}')
    return request["query"]


def wiki_claims(target: Path) -> dict[str, dict[str, str]]:
    """claim_id -> {page, status} for the first occurrence of every claim on the wiki's pages."""
    claims: dict[str, dict[str, str]] = {}
    for path in search_core.candidate_paths(target, False, False):
        relative = path.relative_to(target).as_posix()
        if not relative.startswith("wiki/"):
            continue
        try:
            _data, body = search_core.frontmatter(path.read_text(encoding="utf-8"), relative)
        except (FrontmatterError, UnicodeError):
            raise SystemExit(PARSER_REFUSAL.format(what="recording findability questions")) from None
        for claim in search_core.claims_in(body):
            claims.setdefault(claim["id"], {"page": relative, "status": claim["status"]})
    return claims


def add(target: Path, args: argparse.Namespace, lock: dict[str, Any]) -> dict[str, Any]:
    if not args.user_supplied_wording:
        raise SystemExit(
            "findability questions must be the owner's or a user's own words; pass --user-supplied-wording only "
            "when they supplied this exact wording, never for wording you wrote, completed, corrected, "
            "shortened, or translated"
        )
    records = read_questions(target)
    question = question_from_input(args.question, sys.stdin).strip()
    if not 1 <= len(question) <= MAX_QUESTION_CHARS:
        raise SystemExit(f"question must contain 1 to {MAX_QUESTION_CHARS} characters")
    if not search_core.tokens(question, drop_stopwords=False):
        raise SystemExit("question contains no searchable word")
    findings = secret_screen.scan_text(question)
    if findings:
        raise SystemExit(
            f"question contains a credential-shaped value ({findings[0][1]}); ask the user for a version without it"
        )
    note = args.note or ""
    if len(note) > MAX_NOTE_CHARS or "\n" in note or "\r" in note:
        raise SystemExit(f"note must be one line of at most {MAX_NOTE_CHARS} characters")
    claim_id = args.claim_id
    if not CLAIM_ID.match(claim_id):
        raise SystemExit("claim-id must look like clm-<16 hex digits>")
    claim = wiki_claims(target).get(claim_id)
    if claim is None:
        raise SystemExit(f"claim {claim_id} does not exist in this wiki")
    if claim["status"] not in TARGET_STATUSES:
        raise SystemExit(
            f"claim {claim_id} has status {claim['status']}; a findability question targets an active or disputed claim"
        )
    for record in records:
        if record["claim_id"] == claim_id and record["question"].strip() == question:
            raise SystemExit(f"this question already targets {claim_id} as {record['question_id']}")
    if len(records) >= MAX_QUESTIONS:
        raise SystemExit(
            f"{RELATIVE} holds {MAX_QUESTIONS} questions, the most the check keeps fast; remove one with the user "
            "before adding another"
        )
    taken = {record["question_id"] for record in records}
    question_id = "fq-" + secrets.token_hex(8)
    while question_id in taken:
        question_id = "fq-" + secrets.token_hex(8)
    record = {
        "format": RECORD_FORMAT,
        "question_id": question_id,
        "question": question,
        "claim_id": claim_id,
        "author": args.author,
        "note": note,
        "added_at": utc_now(),
        "lock_id": str(lock.get("lock_id") or ""),
    }
    write_questions(target, records + [record])
    return {"recorded": True, "path": RELATIVE, "question": record}


def remove(target: Path, args: argparse.Namespace) -> dict[str, Any]:
    records = read_questions(target)
    matching = [record for record in records if record["question_id"] == args.question_id]
    if not matching:
        raise SystemExit(f"no findability question {args.question_id}")
    snapshot = create_snapshot(target, args.lock_token, operation="findability-remove", selected_files=[RELATIVE])
    write_questions(target, [record for record in records if record["question_id"] != args.question_id])
    return {"removed": True, "path": RELATIVE, "question": matching[0], "snapshot": snapshot["snapshot"]}


def last_release(target: Path) -> dict[str, str]:
    try:
        manifest = json.loads((target / "meta/manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    return {"version": str(manifest.get("version") or ""), "release_id": str(manifest.get("release_id") or "")}


def judge(record: dict[str, Any], claims: dict[str, dict[str, str]], loaded: Any, limit: int) -> dict[str, Any]:
    """One question ranked over the loaded wiki and its status."""
    target_claim = claims.get(record["claim_id"])
    page = target_claim["page"] if target_claim else None
    try:
        ranking = search_core.rank(loaded, record["question"], limit=limit)
    except search_core.QueryError:
        ranking = None  # Possible only after a hand edit: counts as no match.
    page_rank = ranking.rank_of.get(page) if ranking is not None and page else None
    claim_returned = bool(
        ranking is not None
        and page_rank is not None
        and page_rank <= limit
        and record["claim_id"] in [str(claim.get("id")) for claim in ranking.full(page_rank - 1)["claims"]]
    )
    if target_claim is None:
        status = "target_missing"
    elif target_claim["status"] not in TARGET_STATUSES:
        status = "target_inactive"
    elif claim_returned:
        status = "found"
    elif page_rank is not None and page_rank <= limit:
        status = "found_page_only"
    else:
        status = "not_found"
    return {
        "question_id": record["question_id"],
        "question": record["question"],
        "author": record["author"],
        "claim_id": record["claim_id"],
        "status": status,
        "page": page,
        "page_rank": page_rank,
        "claim_returned": claim_returned,
        "first_result": ranking.ordered[0]["path"] if ranking is not None and ranking.ordered else None,
    }


def check(target: Path, limit: int) -> dict[str, Any]:
    started = time.perf_counter()
    records = read_questions(target)
    results: list[dict[str, Any]] = []
    if records:
        # Users' words alone are measured: wiki scope, word forms and concepts as
        # the query skill defaults, no reformulations, never exhaustive.
        loaded = search_core.load(target)
        if loaded.parser_errors:
            raise SystemExit(PARSER_REFUSAL.format(what="checking findability"))
        claims: dict[str, dict[str, str]] = {}
        for candidate in loaded.candidates:
            if candidate["relative"].startswith("wiki/"):
                for claim in search_core.candidate_claims(candidate):
                    claims.setdefault(claim["id"], {"page": candidate["relative"], "status": claim["status"]})
        results = [judge(record, claims, loaded, limit) for record in records]
    summary = {status: sum(1 for result in results if result["status"] == status) for status in STATUSES}
    return {
        "format": REPORT_FORMAT,
        "target": ".",
        "path": RELATIVE,
        "limit": limit,
        "last_release": last_release(target),
        "questions": len(results),
        "summary": summary,
        "results": results,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "boundary": BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_parser = subparsers.add_parser("add", help="Record one question with its confirmed target claim")
    add_parser.add_argument("--target", required=True)
    add_parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    add_parser.add_argument(
        "--question", required=True,
        help="The verbatim wording, or '-' to read one JSON object {\"query\": ...} from standard input",
    )
    add_parser.add_argument("--claim-id", required=True, help="The confirmed target claim, clm-<16 hex>")
    add_parser.add_argument("--author", required=True, choices=AUTHORS, help="A role, never a name")
    add_parser.add_argument(
        "--user-supplied-wording", action="store_true",
        help="Attest that the owner or a user supplied exactly this wording",
    )
    add_parser.add_argument("--note", default="", help=f"Optional note, one line of at most {MAX_NOTE_CHARS} characters")
    remove_parser = subparsers.add_parser("remove", help="Remove one question after a snapshot of the file")
    remove_parser.add_argument("--target", required=True)
    remove_parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    remove_parser.add_argument("--question-id", required=True)
    check_parser = subparsers.add_parser("check", help="Rank every question on the working files; never blocks")
    check_parser.add_argument("--target", required=True)
    check_parser.add_argument("--lock-token", required=True, help="Token returned by wiki_lock.py acquire")
    check_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    lock = require_lock(target, args.lock_token)
    if not (target / "WIKI.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    if args.command == "check" and not 1 <= args.limit <= 100:
        raise SystemExit("limit must be between 1 and 100")
    refuse_conflict_copies(target)
    if args.command == "add":
        report = add(target, args, lock)
    elif args.command == "remove":
        report = remove(target, args)
    else:
        report = check(target, args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # Windows pipes default to the ANSI code page; output is UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
