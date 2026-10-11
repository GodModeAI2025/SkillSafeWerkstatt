#!/usr/bin/env python3
"""Optionally re-rank candidate notes with the consent-gated decision layer.

BM25 stays the default and the fallback. When the wiki's decision layer is
configured, enabled, and consented, this helper asks the typed provider one
yes/no question per BM25 candidate and returns the notes it ranked above the
retrieval threshold. Any configuration or transport problem degrades to the
deterministic BM25 order instead of failing the query.

The helper is read-only: it never writes into the wiki.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import bm25
import decision_provider
import freshness
import search_wiki
import trust_contract
from frontmatter_contract import FrontmatterError
from verify_release import verify_snapshot
from wiki_filters import matches_selector, validate_selector


NOTE_QUESTION = {
    "de": "Trägt die Notiz „{title}“ ({description}) dazu bei, die gestellte Frage zu beantworten?",
    "en": "Does the note “{title}” ({description}) help answer the given question?",
}


def wiki_language(target: Path) -> str:
    profile = target / "schema/WIKI_PROFILE.md"
    if not profile.is_file():
        return "en"
    try:
        document = search_wiki.frontmatter(profile.read_text(encoding="utf-8"), "schema/WIKI_PROFILE.md")
        language = str(document[0].get("wiki_language") or "")
    except FrontmatterError:
        return "en"
    return language.split("-", 1)[0].casefold() or "en"


def note_candidates(target: Path, query: str, concept_definitions: dict, query_tokens: set, limit: int) -> list[dict[str, Any]]:
    """Rank wiki pages with the same BM25 machinery the standard search uses."""
    candidates: list[dict[str, Any]] = []
    for path in search_wiki.candidate_paths(target, include_sources=False, include_history=False):
        relative = path.relative_to(target).as_posix()
        if not relative.startswith("wiki/") or relative == "wiki/index.md":
            continue
        text = path.read_text(encoding="utf-8")
        try:
            data, body = search_wiki.frontmatter(text, relative)
        except FrontmatterError:
            continue
        if not matches_selector(data, relative, {"kind": "all"}):
            continue
        searchable_body = search_wiki.visible_body(body)
        heading = search_wiki.H1.search(searchable_body)
        title = str(data.get("title") or (heading.group(1).strip() if heading else path.stem))
        candidates.append(
            {
                "path": path,
                "relative": relative,
                "data": data,
                "title": title,
                "body": searchable_body,
                "fields": search_wiki.document_fields({**data, "title": title}, searchable_body),
            }
        )
    corpus = bm25.Corpus(candidate["fields"] for candidate in candidates)
    query_phrase = " ".join(search_wiki.tokens(query, False))
    matched_concept_set = set(
        search_wiki.expand_query(query, concept_definitions)[1]
    )
    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        data = candidate["data"]
        document_concepts = set(search_wiki.as_list(data.get("concepts")))
        score = bm25.score(
            corpus,
            candidate["fields"],
            query_tokens,
            phrase_match=bool(query_phrase and query_phrase in " ".join(search_wiki.tokens(candidate["body"], False))),
            concept_overlap=len(document_concepts & matched_concept_set),
            status=str(data.get("status") or ""),
        )
        if score <= 0:
            continue
        scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], str(item[1]["relative"])))
    return [
        {
            "path": str(item[1]["relative"]),
            "title": str(item[1]["title"]),
            "description": str(item[1]["data"].get("description") or ""),
            "bm25_rank": rank,
        }
        for rank, item in enumerate(scored[:limit], start=1)
    ]


def fallback_report(state: str, reason: str, release: dict, query: str, notes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "state": state,
        "reason": reason,
        "release": release,
        "query": query,
        "fallback": "bm25",
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Target wiki directory")
    parser.add_argument("--query", required=True, help="Question whose candidate notes are re-ranked")
    parser.add_argument("--candidates", type=int, default=16, help="BM25 candidates offered to the decision provider")
    parser.add_argument("--limit", type=int, default=8, help="Maximum notes returned above the retrieval threshold")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not (target / "WIKI.md").is_file() or not (target / "wiki/index.md").is_file():
        raise SystemExit("Target is not an initialized SkillSafeWerkstatt")
    initial_release = verify_snapshot(target)
    if initial_release.get("state") != "ready":
        print(json.dumps({"release": initial_release, "notes": []}, ensure_ascii=False, indent=2))
        return {"wiki_busy": 2, "snapshot_changed": 3}.get(str(initial_release.get("state")), 4)
    if args.candidates < 1 or args.candidates > 100:
        raise SystemExit("candidates must be between 1 and 100")
    if args.limit < 1 or args.limit > 50:
        raise SystemExit("limit must be between 1 and 50")

    language = wiki_language(target)
    template = NOTE_QUESTION.get(language, NOTE_QUESTION["en"])
    concept_definitions = search_wiki.controlled_concepts(target / "schema/CONCEPTS.md")
    query_tokens, matched_concepts, _ = search_wiki.expand_query(args.query, concept_definitions)
    if not query_tokens:
        raise SystemExit("query must contain at least one searchable token")
    bm25_notes = note_candidates(target, args.query, concept_definitions, query_tokens, args.candidates)
    if not bm25_notes:
        print(
            json.dumps(
                fallback_report("no_candidates", "No maintained note carries a term from the query; the decision layer is not needed.", initial_release, args.query, []),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    loaded = decision_provider.load_config(target)
    if loaded["state"] != "active":
        print(json.dumps(fallback_report(loaded["state"], loaded["reason"], initial_release, args.query, bm25_notes[: args.limit]), ensure_ascii=False, indent=2))
        return 0

    config = loaded["config"]
    questions = [
        decision_provider.question_yes_no(
            f"note-{note['bm25_rank']}",
            template.format(title=note["title"], description=note["description"] or "ohne Beschreibung"),
        )
        for note in bm25_notes
    ]
    try:
        request = decision_provider.build_request(config, args.query, questions)
    except decision_provider.DecisionError as exc:
        print(json.dumps(fallback_report("misconfigured", str(exc), initial_release, args.query, bm25_notes[: args.limit]), ensure_ascii=False, indent=2))
        return 0

    api_key = decision_provider.api_key_for(config)
    if api_key is None:
        print(
            json.dumps(
                fallback_report(
                    "provider_unavailable",
                    f"The environment variable {config['api_key_env']} is not set; no provider call was made.",
                    initial_release,
                    args.query,
                    bm25_notes[: args.limit],
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    try:
        response, transport = decision_provider.send_request(
            str(config["endpoint"]),
            api_key,
            request,
            timeout_seconds=int(config["timeout_seconds"]),
            attempts=int(config["attempts"]),
        )
    except decision_provider.DecisionError as exc:
        print(json.dumps(fallback_report("provider_unavailable", str(exc), initial_release, args.query, bm25_notes[: args.limit]), ensure_ascii=False, indent=2))
        return 0

    try:
        answers = decision_provider.validate_response(request, response)
    except decision_provider.DecisionError as exc:
        print(json.dumps(fallback_report("provider_invalid_response", str(exc), initial_release, args.query, bm25_notes[: args.limit]), ensure_ascii=False, indent=2))
        return 0

    scored: list[dict[str, Any]] = []
    for note in bm25_notes:
        answer = answers[f"note-{note['bm25_rank']}"]
        probability = float(answer["probability"])
        scored.append(
            {
                **note,
                "probability": round(probability, 4),
                "confidence": round(decision_provider.confidence_yes_no(probability), 4),
            }
        )
    scored.sort(key=lambda item: (-item["probability"], item["bm25_rank"]))
    threshold = float(config["tau_ret"])
    selected = [note for note in scored if note["probability"] > threshold][: args.limit]
    if not selected:
        print(
            json.dumps(
                {
                    **fallback_report(
                        "no_candidates_above_threshold",
                        f"No note exceeded the retrieval threshold {threshold}; the BM25 order is returned as fallback.",
                        initial_release,
                        args.query,
                        bm25_notes[: args.limit],
                    ),
                    "model": str(config["model"]),
                    "threshold": threshold,
                    "transport": transport,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    final_release = verify_snapshot(target, str(initial_release.get("manifest_sha256") or ""))
    if final_release.get("state") != "ready":
        print(json.dumps({"release": final_release, "notes": []}, ensure_ascii=False, indent=2))
        return {"wiki_busy": 2, "snapshot_changed": 3}.get(str(final_release.get("state")), 4)

    print(
        json.dumps(
            {
                "state": "scored",
                "release": final_release,
                "query": args.query,
                "model": str(config["model"]),
                "threshold": threshold,
                "scored_notes": len(scored),
                "discarded_below_threshold": len(scored) - len(selected),
                "notes": selected,
                "fallback": "none",
                "transport": transport,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
